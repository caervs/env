export PATH=$HOME/src/github.com//caervs/personal/bin:$PATH
export EDITOR=emacs

function devmode {
    # TODO should include lib/py by default
    export PYTHONPATH=~/src/github.com//caervs/public/:~/src/github.com//caervs/personal/lib/py/
}

# TODO reconcile all of my context logic

function pass-context {
    context="$1"
    mode="$2"
    storepath=""

    if [ "$context" == "" ];
    then
	cat ~/.pass-context;
	return
    fi;

    if [ "$context" == "docker" ];
    then
	storepath="$HOME/src/github.com//docker-infra/pass-store";
	gitpath="$HOME/src/github.com//docker-infra/pass-store";
    fi;
    if [ "$context" == "personal" ];
    then
	storepath="$HOME/src/github.com//caervs/private/password-store";
	gitpath="$HOME/src/github.com//caervs/private/";
    fi;
    if [ "$context" == "uhaus" ];
    then
	storepath="$HOME/src/github.com//ulmenhaus/private/password-store";
	gitpath="$HOME/src/github.com//ulmenhaus/private/";
    fi;
    if [ "$context" == "peripheral" ];
    then
	storepath="/Volumes/Key/password-store";
	gitpath="/Volumes/Key/password-store";
    fi;
    if [ "$context" == "test" ];
    then
	tmppath=/tmp/password-store
	mkdir -p $tmppath
	storepath=$tmppath
	gitpath=$tmppath
    fi;

    if [ "" == "$storepath" ];
    then
	echo "Unknown pass-context: $context"
	return 1
    fi;

    if [ "$mode" == "-e" ];
    then
	export PASSWORD_STORE_DIR=$storepath
	export PASSWORD_STORE_GIT=$gitpath
    else
	rm -f ~/.password-store
	unset PASSWORD_STORE_DIR
	unset PASSWORD_STORE_GIT

	ln -s $storepath ~/.password-store
	echo $1 > ~/.pass-context
    fi;
}

function pass-context2 {
    IFS='
'
    for line in $(python3 -m passtools.context $*); do eval $line; done
}
function password-fill {
    IFS='
'
    for line in $(python3 -m passtools.chrome $*); do eval $line; done
}

function gpg-context {
    rm -f ~/.gnupg ~/.ssh

    context="$1"
    sshdir="$HOME/src/github.com//caervs/local/standard_context/ssh";
    if [ "$context" == "standard" ];
    then
	gpgdir="$HOME/src/github.com//caervs/local/standard_context/gnupg";
    fi;
    if [ "$context" == "setup" ];
    then
	gpgdir="$HOME/src/github.com//caervs/local/setup_context/gnupg";
    fi;
    if [ "$context" == "peripheral" ];
    then
	gpgdir="/Volumes/KEY/gnupg"
    fi;

    ln -s $gpgdir ~/.gnupg
    ln -s $sshdir ~/.ssh

}

function fab-context {
    rm -f ~/.highland
    ln -s $HOME/src/github.com//caervs/local/standard_context/fab/highland ~/.highland
}

function pass-gen-ssh-key {
    old_context=$(pass-context)
    pass-context peripheral -e
    keyname=$1
    pass generate --no-symbols rsa/$keyname 40
    ssh-keygen -f $HOME/src/github.com//caervs/local/standard_context/ssh/$keyname -P $(pass show rsa/$keyname)
    pass-context $old_context
}

function add-keypair {
    pass-context peripheral -e
    keyname=$1
    pass_reference=$2
    ssh-add-with-password $HOME/src/github.com//caervs/local/rsa/$keyname $pass_reference
    pass-context $old_context
}

. ~/src/github.com//zx2c4/password-store/src/completion/pass.bash-completion

if [ -f `brew --prefix`/etc/bash_completion ]; then
    . `brew --prefix`/etc/bash_completion
fi


alias blender='~/Downloads/Blender/blender.app/Contents/MacOS/blender'

function bootstrap {
    ln -s ~/src/github.com//caervs/personal/profiles/emacs.el ~/.emacs
    ln -s ~/src/github.com//caervs/personal/profiles/xonshrc.py ~/.xonshrc
}

alias euler_env='cd ~/src/github.com//caervs/miniprojects; . ./project-euler/activate'
alias ee=euler_env


# HACK until jex can be used
function trackit-env {
    export TRACKIT_SLACK_TOKEN=$(pass show network/slack-token)
    export TRACKIT_BOT_MASTER="rabrams"
    export TRACKIT_USERS="rabrams"
    export TRACKIT_CHANNEL="#hackyducks"
    export TRACKIT_PUBLIC_ENDPOINT="https://trackit.ulmenhaus.com"
}

#alias br-clean="git branch -dq $(git branch | grep -v '^\*') 2>&1 | grep '^error: ' | sed 's/^error: //'"
