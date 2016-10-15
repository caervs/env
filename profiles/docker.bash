function work-context {
    # only highland is supported for now
    cd ~/src/github.com/docker/highland
}

function mega-context {
    # only highland is supported for now
    cd ~/src/github.com/docker/saas-mega
}

function set-mail-shortcuts {
    defaults write com.apple.mail NSUserKeyEquivalents '{"Office Notifications"="^o"; "Company Notifications"="^c"; "Birthdays"="^b"; "Welcomes"="^w";}'; killall Mail; open /Applications/Mail.app
}

function highland_dev {
    docker run --rm -it --net host -v /var/run/docker.sock:/var/run/docker.sock --privileged -v ~/.gnupg-root:/root/.gpg -v ~/.dockercfg:/root/.dockercfg -v ~/src/github.com/docker-infra/pass-store:/root/.password-store -v ~/src/github.com/docker/highland/:/highland/ -v ~/src/github.com/docker/saas-mega/:/saas-mega/ -v /Users/rabrams:/rabrams -v ~/src/github.com/docker-infra/docker-ca:/dockerca highland_dev
}

function prod-ak {
    password=$(pass show docker/dockerhub)
    token=$(curl -X POST -H "content-type: application/json" -d "{\"username\": \"rabrams\", \"password\": \"$password\"}" https://hub.docker.com/v2/users/login/ | jq -r .token)
    accesskey=$(curl -X POST -H "Authorization: JWT $token" https://hub.docker.com/v2/users/rabrams/accesskeys/ | jq .secret)
    echo "export ACCESSKEY=$accesskey" | pbcopy
}

function prod-ak-highland {
    password=$(pass show dev/teams/highland/production/hub/pass)
    token=$(curl -X POST -H "content-type: application/json" -d "{\"username\": \"highland\", \"password\": \"$password\"}" https://hub.docker.com/v2/users/login/ | jq -r .token)
    accesskey=$(curl -X POST -H "Authorization: JWT $token" https://hub.docker.com/v2/users/highland/accesskeys/ | jq .secret)
    echo "export ACCESSKEY=$accesskey" | pbcopy
}

function stage-ak {
    password=$(pass show docker/dockerhub-staging)
    token=$(curl -X POST -H "content-type: application/json" -d "{\"username\": \"rabrams\", \"password\": \"$password\"}" https://hub-stage.docker.com/v2/users/login/ | jq -r .token)
    accesskey=$(curl -X POST -H "Authorization: JWT $token" https://hub-stage.docker.com/v2/users/rabrams/accesskeys/ | jq .secret)
    echo "export ACCESSKEY=$accesskey" | pbcopy
}

function stage-ak-highland {
    password=$(pass show dev/teams/highland/staging/hub/pass)
    token=$(curl -X POST -H "content-type: application/json" -d "{\"username\": \"highland\", \"password\": \"$password\"}" https://hub-stage.docker.com/v2/users/login/ | jq -r .token)
    accesskey=$(curl -X POST -H "Authorization: JWT $token" https://hub-stage.docker.com/v2/users/highland/accesskeys/ | jq .secret)
    echo "export ACCESSKEY=$accesskey" | pbcopy
}

function prod-token {
    password=$(pass show dev/teams/highland/production/hub/pass)
    token=$(curl -X POST -H "content-type: application/json" -d "{\"username\": \"highland\", \"password\": \"$password\"}" https://hub.docker.com/v2/users/login/ | jq -r .token)
    echo $token
    # accesskey=$(curl -X POST -H "Authorization: JWT $token" https://hub.docker.com/v2/users/highland/accesskeys/ | jq .secret)
    # echo "export ACCESSKEY=$accesskey" | pbcopy
}
