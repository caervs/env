import builtins
import collections
import contextlib
import functools
import httplib2
import itertools
import json
import os
import subprocess
import tempfile
import threading
import time

import xonsh.ansi_colors
import requests

from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage
from requests.auth import HTTPBasicAuth
from termcolor import colored

from xonshlib import ENV

OSA_TEMPLATE = """
tell application "Google Chrome"
   tell window 1
       tell active tab
           open location "{formurl}"
       end tell
   end tell

   delay 3
   tell window 1
       tell active tab
           {javascript}
       end tell
   end tell
end tell
"""

JS_INDENT = " " * 11
# TODO these templates don't support some special characters
SET_LINE = JS_INDENT + '''execute javascript ("document.getElementById('{objid}').value = '{value}'")'''
SUBMIT_LINE = JS_INDENT + '''execute javascript ("document.getElementById('{buttonid}').click()")'''

VPN_OSA_TEMPLATE = """
on run args
    set connection to "{connection}"
    tell application "Tunnelblick"
        if connection = "-"
            disconnect All
        else
            connect connection
            get state of first configuration where name = connection
            repeat until result = "CONNECTED"
                delay 1
                get state of first configuration where name = connection
            end repeat
        end if
    end tell
end run
"""


class PasswordManager(object):
    def __init__(self, pass_stores):
        self.pass_stores = pass_stores
        self.reverse_stores = {
            self.combine(value): key
            for key, value in pass_stores.items()
        }

    @staticmethod
    def combine(pathish):
        return pathish if isinstance(pathish, str) else os.path.join(*pathish)

    def get_context(self):
        return self.reverse_stores.get(ENV.get('PASSWORD_STORE_DIR'), 'none')

    def set_context(self, args, stdin=None):
        name, = args
        if name == '-':
            if "PASSWORD_STORE_DIR" in ENV:
                del ENV['PASSWORD_STORE_DIR']
            if "PASSWORD_STORE_GIT" in ENV:
                del ENV['PASSWORD_STORE_GIT']
        else:
            store = self.pass_stores[args[0]]
            if isinstance(store, str):
                ENV['PASSWORD_STORE_DIR'] = store
                ENV['PASSWORD_STORE_GIT'] = store
            else:
                git_dir, store_dir = store
                ENV['PASSWORD_STORE_DIR'] = os.path.join(git_dir, store_dir)
                ENV['PASSWORD_STORE_GIT'] = git_dir

    def complete_line(self, prefix, line, begidx, endidx, ctx):
        if not line.startswith("pass"):
            return

        if "PASSWORD_STORE_DIR" not in ENV:
            return {"No pass context", ""}

        parts = os.path.split(prefix)
        path_so_far = os.path.join(*parts[:-1])
        subdir = os.path.join(ENV["PASSWORD_STORE_DIR"], path_so_far)
        all_files = os.listdir(subdir)
        process_filename = lambda filename : os.path.join(filename, "") \
                           if not filename.endswith(".gpg") \
                           else filename[:-4]
        is_match = lambda filename: filename.startswith(parts[-1])
        is_candidate = lambda filename: os.path.isdir(os.path.join(subdir, filename)) or \
                       filename.endswith(".gpg")
        completions = map(process_filename,
                          filter(is_candidate, filter(is_match, all_files)))
        return {
            os.path.join(path_so_far, completion)
            for completion in completions
        }

    def get_entry(self, args, is_json=True):
        os.environ['PASSWORD_STORE_DIR'] = ENV['PASSWORD_STORE_DIR']
        os.environ['PASSWORD_STORE_GIT'] = ENV['PASSWORD_STORE_GIT']
        path, = args
        output = subprocess.check_output(["pass", "show",
                                          path]).decode("utf-8")
        return json.loads(output) if is_json else output

    def get_env(self, args, stdin=None):
        ENV.update(self.get_entry(args))

    def submit_data(self, args, stdin=None):
        params = self.get_entry(args)
        javascript = "{}\n{}".format(
            "\n".join(
                SET_LINE.format(objid=objid, value=value)
                for objid, value in params['fields'].items()),
            SUBMIT_LINE.format(buttonid=params['buttonid']))

        osascript = OSA_TEMPLATE.format(
            formurl=params['url'], javascript=javascript)
        proc = subprocess.Popen(
            ['osascript'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        proc.communicate(osascript.encode('utf-8'))
        proc.wait()

    def add_ssh_key(self, args, stdin=None):
        key_body = self.get_entry(args, False)
        # TODO file should be given same name as pass entry so
        # ssh-add -l is meaningful
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(key_body.encode('utf-8'))
        try:
            subprocess.check_call(["ssh-add", f.name])
        finally:
            os.remove(f.name)


class DockerClusterManager(object):
    def __init__(self, clusters):
        # TODO validate clusters
        self.clusters = clusters

    def get_cluster_env(self, args, stdin=None):
        name, = args
        for key in list(ENV):
            if key.startswith("DOCKER_"):
                del ENV[key]
        if "KUBECONFIG" in ENV:
            del ENV["KUBECONFIG"]
        if name == '-':
            return
        elif "/" in name:
            self.cloud_swarm_env(name)
        elif name not in self.clusters:
            self.docker_machine_env(name)
        else:
            params = self.clusters[name]
            ENV["DOCKER_HOST"] = params['host']
            if "vpn" in params:
                vpn((params['vpn'], ))
            if 'certs' in params:
                ENV["DOCKER_CERT_PATH"] = params['certs']
                ENV["DOCKER_TLS_VERIFY"] = "1"

        ENV["DOCKER_MACHINE"] = name

    @staticmethod
    def docker_machine_env(name):
        output = subprocess.check_output(['docker-machine', 'env', name])
        for line in output.decode('utf-8').split("\n"):
            if line.startswith("export "):
                cmd = line[len("export "):]
                key, value = cmd.split("=")
                ENV[key] = json.loads(value)

    @staticmethod
    def _existing_swarm_env(namespace, cluster):
        inspect = subprocess.check_output([
            'docker', 'inspect', "client_proxy_{}_{}".format(
                namespace, cluster)
        ])
        attrs = json.loads(inspect.decode("utf-8"))
        port = list(
            attrs[0]['NetworkSettings']['Ports'].values())[0][0]['HostPort']
        ENV["DOCKER_HOST"] = "tcp://localhost:{}".format(port)

    def cloud_swarm_env(self, name):
        namespace, cluster = name.split("/")
        try:
            return self._existing_swarm_env(namespace, cluster)
        except subprocess.CalledProcessError:
            subprocess.check_output([
                'docker', 'run', '-it', '--rm', '-v',
                '/var/run/docker.sock:/var/run/docker.sock',
                'dockercloud/client', '--swarm', name
            ])
            return self._existing_swarm_env(namespace, cluster)


def command_for_container_config(config):
    volumes = " ".join("-v {}:{}".format(key, value)
                       for key, value in config.get("volumes", {}).items())
    return "docker run {wd} {it} {rm} {privileged} {net} {volumes} {image}".format(
        it=("-it" if config.get("it") else ""),
        rm=("--rm" if config.get("rm") else ""),
        net=("--net {}".format(config['net']) if "net" in config else ""),
        privileged=("--privileged" if config.get("privileged") else ""),
        wd=("-w {}".format(config['workdir']) if "workdir" in config else ""),
        volumes=volumes,
        image=config['image'], )


def docker_clean(args, stdin=None):
    for art_type in ['service', 'plugin', 'container']:
        ls_flag = "-aq" if art_type == 'container' else '-q'
        output = subprocess.check_output(['docker', art_type, 'ls', ls_flag])
        ids = list(output.decode("utf-8").split("\n")[:-1])
        if not ids:
            print("No {}s".format(art_type))
            continue
        print("Cleaning {}s".format(art_type))
        rm_flag = [] if art_type == 'service' else ['-f']
        command = ["docker", art_type, "rm"] + rm_flag + ids
        subprocess.check_output(command)


# TODO make into a binary so that "git br-clean" will also work and can be invoked en
# masse using gr
def git_clean(args, stdin=None):
    branches = subprocess.check_output(["git",
                                        "branch"]).decode("utf-8").split("\n")
    other_branches = []
    current_branch = None
    for branchline in branches:
        branch = branchline.strip(" ")
        if branch.startswith("* "):
            current_branch = branch[2:]
        elif branch:
            other_branches.append(branch)

    if not current_branch:
        print("No current branch found")
    elif current_branch != 'master':
        print("fatal: trying to run clean from a branch other than master")
    elif not other_branches:
        return
    else:
        subprocess.call(["git", "branch", "-d"] + other_branches)


class PythonPathSetter(object):
    def __init__(self, paths):
        self.paths = dict(paths)

    def set_paths(self, args, stdin=None):
        if args == []:
            paths = list(self.paths.values())
            antipaths = []
        elif args == ["-"]:
            paths = []
            antipaths = list(self.paths.values())
        else:
            antipaths = [
                self.paths[arg[1:]] for arg in args if arg.startswith("-")
            ]
            paths = [
                self.paths[arg] for arg in args if not arg.startswith("-")
            ]

        current_paths = ENV["PYTHONPATH"]
        cleaned = [
            path for path in current_paths if path not in paths + antipaths
        ]
        ENV["PYTHONPATH"] = paths + cleaned


class Task(object):
    def __init__(self, taskid, description, user_labels, driver_labels=()):
        self.taskid = taskid
        self.description = description
        self.user_labels = user_labels
        self.driver_labels = driver_labels
        self._essential_attrs = (taskid, description, user_labels,
                                 driver_labels)

    def __hash__(self):
        return hash(self._essential_attrs)

    def __eq__(self, other):
        return self._essential_attrs == other._essential_attrs


class TaskBackend(object):
    def get_tasks(self):
        raise NotImplementedError


class GmailBackend(TaskBackend):
    scopes = 'https://www.googleapis.com/auth/gmail.readonly'

    def __init__(self, address, pass_manager, token_root):
        self.address = address
        self.pass_manager = pass_manager
        self.token_root = token_root

    @contextlib.contextmanager
    def _get_service(self):
        from apiclient import discovery
        secret_body = self.pass_manager.get_entry(
            ["{}.secret".format(self.token_root)], is_json=False)
        token_body = self.pass_manager.get_entry(
            ["{}.token".format(self.token_root)], is_json=False)
        with tempfile.NamedTemporaryFile(delete=False) as secret_file:
            secret_file.write(secret_body.encode('utf-8'))
        with tempfile.NamedTemporaryFile(delete=False) as token_file:
            token_file.write(token_body.encode('utf-8'))
        try:
            credentials = self._get_credentials(secret_file.name,
                                                token_file.name)
            http = credentials.authorize(httplib2.Http())
            yield discovery.build('gmail', 'v1', http=http)
        finally:
            os.remove(secret_file.name)
            os.remove(token_file.name)

    def _get_credentials(self, secret_path, token_path):
        store = Storage(token_path)
        credentials = store.get()
        if not credentials or credentials.invalid:
            flow = client.flow_from_clientsecrets(secret_path, self.scopes)
            flow.user_agent = 'aggretask'
            credentials = tools.run_flow(flow, store)
        return credentials

    def _get_messages_with_query(self, service, query):
        response = service.users().messages().list(
            userId='me', q=query).execute()
        messages = []
        if 'messages' in response:
            messages.extend(response['messages'])

        while 'nextPageToken' in response:
            page_token = response['nextPageToken']
            response = service.users().messages().list(
                userId='me', q=query, pageToken=page_token).execute()
            messages.extend(response['messages'])
        return messages

    def _get_messages(self, service):
        queries = ["is:unread", "label:inbox"]
        get = functools.partial(self._get_messages_with_query, service)
        return {
            message_meta['id']
            for message_meta in itertools.chain(*map(get, queries))
        }

    def get_tasks(self):
        with self._get_service() as service:
            return list(self._get_tasks_with_service(service))

    def _get_tasks_with_service(self, service):
        mids = self._get_messages(service)
        response = service.users().labels().list(userId='me').execute()
        label_names = {
            label['id']: label['name']
            for label in response['labels']
        }

        for mid in mids:
            message = service.users().messages().get(
                userId='me', id=mid).execute()
            labels = message['labelIds']
            headers = message['payload']['headers']
            subject = ""
            for header in headers:
                if header['name'] == 'Subject':
                    subject = header['value']
                    break
            mlabels = tuple(label_names[label] for label in labels)
            mlabels = tuple(lname for lname in mlabels
                            if lname.upper() != lname)
            driver_label = "source/{}".format(self.address)
            yield Task(
                taskid=mid,
                description=subject,
                user_labels=mlabels,
                driver_labels=(driver_label, ))


class GitHubBackend(TaskBackend):
    def __init__(self, username, pass_manager, pass_location):
        self.username = username
        self.pass_manager = pass_manager
        self.pass_location = pass_location

    def get_tasks(self):
        token = self.pass_manager.get_entry(
            [self.pass_location], is_json=False).strip()
        response = requests.get(
            'https://api.github.com/issues',
            auth=HTTPBasicAuth(self.username, token))
        for issue in response.json():
            driver_label = 'source/github.com/{}'.format(
                issue['repository']['full_name'])
            user_labels = [label['name'] for label in issue['labels']]
            yield Task(
                taskid=issue['id'],
                description=issue['title'],
                user_labels=tuple(user_labels),
                driver_labels=(driver_label, ))


class ChromeBackend(TaskBackend):
    def __init__(self, inbox_label="bookmark_bar/Inbox", labels=()):
        self.inbox_label = inbox_label
        self.labels = labels

    def get_tasks(self):
        path = os.path.expanduser(
            "~/Library/Application Support/Google/Chrome/Default/Bookmarks")
        with open(path) as bookmarks:
            roots = json.load(bookmarks)['roots']
        for rootname, attrs in roots.items():
            if rootname.startswith("sync"):
                continue
            yield from self._get_tasks_from_dir(attrs['children'], rootname)

    def _get_tasks_from_dir(self, children, dirname):
        for child in children:
            if "url" in child:
                if dirname in self.labels:
                    yield Task(
                        taskid=child['id'],
                        description=child['name'],
                        # TODO group together instances in different folders?
                        user_labels=(dirname, ),
                        driver_labels=("source/chrome", ))
                elif dirname == self.inbox_label:
                    yield Task(
                        taskid=child['id'],
                        description=child['name'],
                        user_labels=(),
                        driver_labels=("source/chrome", ))

            else:
                subdirname = "/".join([dirname, child['name']])
                yield from self._get_tasks_from_dir(child['children'],
                                                    subdirname)


class TaskManager(object):
    def __init__(self, backends):
        self.backends = backends

    def get_all_tasks(self):
        return set().union(*(backend.get_tasks() for backend in self.backends))

    def print_tasks(self, args, stdin=None):
        all_tasks = self.get_all_tasks()
        by_label = collections.defaultdict(list)
        for task in all_tasks:
            if not task.user_labels:
                by_label[None].append(task)
            else:
                for label in task.user_labels:
                    by_label[label].append(task)
        self._display_tasks(by_label)

    def _display_tasks(self, by_label):
        red_labels = {
            'priority/p0': 'Active',
            None: 'Inbox',
        }
        red_tasks = {}
        yellow_tasks = {}
        for label, tasks in by_label.items():
            task_dict = red_tasks if label in red_labels else yellow_tasks
            task_dict[label] = len(tasks)

        if not (red_tasks or yellow_tasks):
            return

        largest_group = max(0, *itertools.chain(red_tasks.values(),
                                                yellow_tasks.values()))
        column_width = len(str(largest_group))
        for red_label, tcount in self._sort_by_value_desc(red_tasks):
            buffer_width = column_width - len(str(tcount))
            col_buffer = " " * buffer_width
            print(colored("{}{} {}".format(col_buffer, tcount, red_labels[
                red_label]), 'red'))
            breakdown = collections.defaultdict(int)
            for task in by_label[red_label]:
                breakdown[task.driver_labels[0]] += 1
            for sublabel, scount in self._sort_by_value_desc(breakdown):
                print(" " * column_width, scount, sublabel)

        for yellow_label, tcount in self._sort_by_value_desc(yellow_tasks):
            buffer_width = column_width - len(str(tcount))
            col_buffer = " " * buffer_width
            print(colored("{}{} {}".format(col_buffer, tcount, yellow_label),
                          'yellow'))

    @staticmethod
    def _sort_by_value_desc(d):
        return reversed(sorted(d.items(), key=lambda item: item[1]))


def vpn(args, stdin=None):
    connection, = args
    osascript = VPN_OSA_TEMPLATE.format(connection=connection)
    proc = subprocess.Popen(
        ['osascript'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    proc.communicate(osascript.encode('utf-8'))
    proc.wait()


class NavigationManager(object):
    def __init__(self, startdir, percentage=25, before=True, horizantal=True):
        self.startdir = startdir
        self.percentage = percentage
        self.before = before
        self.horizantal = horizantal

    def _watch_for_changes(self, tail_proc):
        for line in tail_proc.stdout:
            path = line.decode("utf8").strip()
            if os.path.isdir(path):
                os.chdir(path)
                ENV["PWD"] = path
                prompt = builtins.__xonsh_shell__.prompt_formatter(
                    ENV["PROMPT"])
                print(
                    '\r{}\033[K'.format(
                        xonsh.ansi_colors.ansi_partial_color_format(prompt)),
                    end='')
            else:
                editor = os.environ.get("EDITOR", "emacs")
                # creating a subproc from a thread seems to break xonsh
                # unfortunately so write a command to xonsh instead
                subprocess.check_call([
                    "tmux", "send", "-t", os.environ["TMUX_PANE"],
                    "{} {}".format(editor, path), "ENTER"
                ])
                # could also check to see if emacs is open and send a C-x C-f to it

    def _sidebar_navigate(self):
        tmux_args = ['tmux', 'split-window', '-p', str(self.percentage)]
        if self.before:
            tmux_args.append('-b')
        if self.horizantal:
            tmux_args.append('-h')
        fifo_path = tempfile.NamedTemporaryFile(delete=False).name
        tmux_args.extend([
            "bash", "-c",
            "PATH={} EDITOR=write-to-fifo WRITE_FIFO_PATH={} NNN_USE_EDITOR=1 NNN_DE_FILE_MANAGER=write-to-fifo nnn {}".
            format(os.environ.get("PATH", ""), fifo_path, self.startdir)
        ])
        subprocess.check_call(tmux_args)
        tail_proc = subprocess.Popen(
            ["tail", "-F", fifo_path], stdout=subprocess.PIPE)
        t = threading.Thread(
            target=self._watch_for_changes, args=(tail_proc, ), daemon=True)
        # HACK Difficult to tell when the corresponding nnn proc has ended so just kill
        # after two hours
        t.start()
        time.sleep(2 * 60 * 60)
        tail_proc.kill()
        # TODO exception handling
        os.remove(fifo_path)

    def sidebar_navigate(self, args, stdin=None):
        t = threading.Thread(target=self._sidebar_navigate, daemon=True)
        t.start()


def goto_ann_dir(args, stdin=None):
    url, = args
    env = dict(os.environ)
    env.update({
        "ANN_DIR": ENV["ANN_DIR"],
        "PYTHONPATH": ':'.join(ENV["PYTHONPATH"]),
    })
    p = subprocess.Popen(
        ["/usr/local/bin/python3", "-m", "ann", "wd", url],
        stdout=subprocess.PIPE,
        env=env, )
    out, _ = p.communicate()
    if p.wait():
        raise Exception("non-zero exit code")
    target = out.decode("utf-8").strip()
    os.chdir(target)
    ENV["PWD"] = target
