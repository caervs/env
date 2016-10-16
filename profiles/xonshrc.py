import json
import os
import subprocess

ENV = __xonsh_env__

ENV['XONSH_SHOW_TRACEBACK'] = True

HOME = ENV["HOME"]
GH = os.path.join(HOME, "src", "github.com")
GH_ALIAS = "caervs"

pass_stores = {
    "personal": os.path.join(GH, GH_ALIAS, "private", "password-store"),
    "docker": os.path.join(GH, "docker-infra", "pass-store"),
    "uhaus": os.path.join(GH, "ulmenhaus", "private", "password-store"),
}

reverse_pass_stores = {value: key for key, value in pass_stores.items()}
lock_glyph = b"\xF0\x9F\x94\x92".decode("utf-8")
whale_glyph = b"\xF0\x9F\x90\xB3".decode("utf-8")
local_machine = b"pi\xC3\xB1ata".decode("utf-8")

prompt_template = "{pass_color}{lock_glyph} {pass_context} \
{docker_color}{whale_glyph} {docker_machine} {dir_color}{short_wd}{end}"

ENV['PROMPT'] = lambda : prompt_template.format(
    pass_color="{GREEN}" if "PASSWORD_STORE_DIR" in ENV else "{RED}",
    lock_glyph=lock_glyph,
    pass_context=reverse_pass_stores.get(ENV.get('PASSWORD_STORE_DIR'), 'none'),
    docker_color="{BLUE}",
    whale_glyph=whale_glyph,
    docker_machine=ENV.get("DOCKER_MACHINE", local_machine),
    dir_color="{YELLOW}",
    short_wd=shorten_dir(ENV['PWD']),
    end="{NO_COLOR} {prompt_end} ")


def shorten_dir(fulldir):
    prefix = os.path.join(GH, "")
    if fulldir.startswith(prefix):
        return fulldir[len(prefix):]
    return fulldir


def pass_context(args, stdin=None):
    name, = args
    if name == '-':
        del ENV['PASSWORD_STORE_DIR']
    else:
        ENV['PASSWORD_STORE_DIR'] = pass_stores[args[0]]


def docker_machine_env(args, stdin=None):
    name, = args
    if name == '-':
        for key in list(ENV):
            if key.startswith("DOCKER_"):
                del ENV[key]
        return

    output = subprocess.check_output(['docker-machine', 'env', name])
    for line in output.decode('utf-8').split("\n"):
        if line.startswith("export "):
            cmd = line[len("export "):]
            key, value = cmd.split("=")
            ENV[key] = json.loads(value)
    ENV["DOCKER_MACHINE"] = name


def pass_complete(prefix, line, begidx, endidx, ctx):
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
    completions = map(process_filename, filter(is_match, all_files))
    return {os.path.join(path_so_far, completion)
            for completion in completions}


aliases['set_completers'] = "completer add pass pass_complete start"

aliases['pc'] = pass_context
aliases['dm'] = docker_machine_env
aliases['src'] = "cd ~/src/github.com/"
clear
set_completers
