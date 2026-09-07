#!/bin/bash
# Run ansible through the wrapper against a real bastion in docker.
#
# Needs docker and ansible-playbook in PATH. Every container, network and
# temporary file is removed on exit.
set -euo pipefail

# the container and network names carry the pid, so that two runs on the same
# machine do not remove each other's containers
bastion_image=${BASTION_IMAGE:-ovhcom/the-bastion:sandbox}
target_image=${TARGET_IMAGE:-bastion-wrapper-test-target-image}
network=${NETWORK:-bastion-wrapper-test-$$}
bastion=${BASTION_CONTAINER:-bastion-wrapper-test-bastion-$$}
target=${TARGET_CONTAINER:-bastion-wrapper-test-target-$$}
account=ansible
admin_account=poweruser
remote_user=deploy

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
wrapper=${WRAPPER:-$repo/sshwrapper.py}
wrapper_dir=$(cd "$(dirname "$wrapper")" && pwd)
workdir=$(mktemp -d)

log() {
    printf '\n=== %s\n' "$*"
}

remove_containers() {
    docker rm -f "$bastion" "$target" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
}

cleanup() {
    remove_containers
    rm -rf "$workdir"
}
trap cleanup EXIT INT TERM

log "starting the bastion and the target"
remove_containers
# the sandbox tag moves, and a stale local image answers a different suite than
# a fresh one in CI
docker pull -q "$bastion_image" >/dev/null
docker network create "$network" >/dev/null
docker build -q -t "$target_image" -f "$here/Dockerfile.target" "$here" >/dev/null
docker run -d --name "$target" --network "$network" "$target_image" >/dev/null
docker run -d --name "$bastion" --network "$network" -p 127.0.0.1::22 "$bastion_image" >/dev/null

for _ in $(seq 120); do
    docker logs "$bastion" 2>&1 | grep -q 'sandbox container is running' && break
    sleep 1
done
docker logs "$bastion" 2>&1 | grep -q 'sandbox container is running' || {
    echo "the bastion did not start" >&2
    docker logs "$bastion" >&2
    exit 1
}

bastion_port=$(docker port "$bastion" 22/tcp | head -1 | cut -d: -f2)
target_ip=$(docker inspect "$target" \
    --format "{{(index .NetworkSettings.Networks \"$network\").IPAddress}}")

log "creating the bastion accounts"
ssh-keygen -q -t ed25519 -N '' -C "$admin_account" -f "$workdir/id_admin"
ssh-keygen -q -t ed25519 -N '' -C "$account" -f "$workdir/id_ansible"

# reads the public key from stdin, where it would otherwise prompt for it
docker exec -i "$bastion" \
    /opt/bastion/bin/admin/setup-first-admin-account.sh "$admin_account" auto \
    < "$workdir/id_admin.pub" >/dev/null

# the bastion parses the command line it receives, hence the double quoting
osh() {
    ssh -q -T -i "$workdir/id_admin" -p "$bastion_port" \
        -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o BatchMode=yes "$admin_account@127.0.0.1" -- --osh "$@"
}
osh accountCreate --account "$account" --uid-auto --always-active \
    --public-key "\"$(cat "$workdir/id_ansible.pub")\""

# the bastion knows no host key for the freshly started target
osh accountModify --account "$account" \
    --egress-strict-host-key-checking accept-new
osh accountAddPersonalAccess --account "$account" --host "$target_ip" \
    --user "$remote_user" --port 22

# file transfers need their protocol allowed on top of the user access
for protocol in scpupload scpdownload sftp; do
    osh accountAddPersonalAccess --account "$account" --host "$target_ip" \
        --port 22 --protocol "$protocol"
done

log "authorizing the bastion egress key on the target"
egress_key=$(docker exec "$bastion" sh -c "cat /home/$account/.ssh/id_*.pub")
docker exec "$target" sh -c "
    set -e
    mkdir -p /home/$remote_user/.ssh
    echo '$egress_key' >> /home/$remote_user/.ssh/authorized_keys
    chmod 700 /home/$remote_user/.ssh
    chmod 600 /home/$remote_user/.ssh/authorized_keys
    chown -R $remote_user: /home/$remote_user/.ssh"

cat > "$workdir/ansible.cfg" <<EOF
[defaults]
host_key_checking = False
inventory = $workdir/hosts
[ssh_connection]
pipelining = True
ssh_executable = $wrapper
scp_executable = $wrapper_dir/scpbastion.sh
sftp_executable = $wrapper_dir/sftpbastion.sh
# scp speaks the sftp protocol since OpenSSH 9, which the scp wrapper cannot proxy
scp_extra_args = -O
# the bastion host key changes on every run, and the wrapper hands these over
ssh_args = -C -o ControlMaster=auto -o ControlPersist=60s -o UserKnownHostsFile=/dev/null
EOF

cat > "$workdir/hosts" <<EOF
[all]
target ansible_host=$target_ip

[all:vars]
ansible_user=$remote_user
EOF

cat > "$workdir/hosts-bastion" <<EOF
[all]
target ansible_host=$target_ip

[all:vars]
ansible_user=$remote_user
bastion_user=$account
bastion_host=127.0.0.1
bastion_port=$bastion_port
EOF

cat > "$workdir/bastion.yml" <<EOF
bastion_user: $account
bastion_host: 127.0.0.1
bastion_port: $bastion_port
EOF

# the bastion user is missing on purpose, the inventory below carries it
cat > "$workdir/bastion-no-user.yml" <<EOF
bastion_host: 127.0.0.1
bastion_port: $bastion_port
EOF

cat > "$workdir/hosts-bastion-user" <<EOF
[all]
target ansible_host=$target_ip

[all:vars]
ansible_user=$remote_user
bastion_user=$account
EOF

export ANSIBLE_CONFIG="$workdir/ansible.cfg"
export ANSIBLE_PRIVATE_KEY_FILE="$workdir/id_ansible"
unset BASTION_USER BASTION_HOST BASTION_PORT

# a warm ControlPersist master answers without ever running the wrappers, and
# hides both an unresolved bastion host and a wrapper that is never called, so
# every run gets a control socket directory of its own
playbook() {
    local name=$1
    shift
    local control_path
    # mktemp replaces the XXXXXX suffix with random characters
    control_path=$(mktemp -d "$workdir/control-path-XXXXXX")
    ANSIBLE_SSH_CONTROL_PATH_DIR="$control_path" \
        ansible-playbook "$here/playbooks/$name.yml" "$@"
}

# ansible logs a failing "ssh -O check" at -vvv and never fails a play on it,
# so the operations that stay local are checked against the wrapper itself
log "local ssh operations handed over to ssh"
version=$("$wrapper" -V 2>&1) || true
case "$version" in
    OpenSSH*) ;;
    *)
        echo "the wrapper did not hand -V over to ssh: $version" >&2
        exit 1
        ;;
esac

# ssh exits non-zero on a control socket that does not exist, the wrapper has
# to report that rather than crash on arguments holding no command
control_master=$("$wrapper" -o ControlPath="$workdir/no-such-socket" \
    -O stop "$target_ip" 2>&1) || true
case "$control_master" in
    *Traceback*)
        echo "the wrapper crashed on a control master operation:" >&2
        echo "$control_master" >&2
        exit 1
        ;;
esac

log "playbook environment as the only source of the bastion vars"
BASTION_CONF_FILE=/nonexistent playbook playbook-env \
    -e bastion_user="$account" \
    -e bastion_host=127.0.0.1 \
    -e bastion_port="$bastion_port" \
    -e ansible_python_interpreter=/usr/bin/python3

# the wrapper runs ansible-inventory itself, ANSIBLE_INVENTORY reaches both
log "inventory as the only source of the bastion vars"
BASTION_CONF_FILE=/nonexistent ANSIBLE_INVENTORY="$workdir/hosts-bastion" \
    playbook inventory

log "configuration file as the only source of the bastion vars"
BASTION_CONF_FILE="$workdir/bastion.yml" playbook config-file

# in a subshell, an export would otherwise reach the runs below
log "environment variables as the only source of the bastion vars"
(
    export BASTION_USER="$account"
    export BASTION_HOST=127.0.0.1
    export BASTION_PORT="$bastion_port"
    BASTION_CONF_FILE=/nonexistent playbook os-env-vars
)

log "configuration file and inventory sharing the bastion vars"
BASTION_CONF_FILE="$workdir/bastion-no-user.yml" \
    ANSIBLE_INVENTORY="$workdir/hosts-bastion-user" playbook mixed-sources

# every source but the configuration file is turned off, and the wrapper has to
# connect on that one alone without reading the others
log "configuration file as the only source enabled"
BASTION_CONF_FILE="$workdir/bastion.yml" \
    BASTION_PLAYBOOK_ENV_ENABLED=0 \
    BASTION_ANSIBLE_INVENTORY_ENABLED=0 \
    BASTION_OS_ENV_ENABLED=0 \
    playbook config-file

# the inventory is the only source holding the bastion vars here, turning it off
# has to fail rather than read it anyway
log "inventory source turned off"
disabled=$(BASTION_CONF_FILE=/nonexistent \
    ANSIBLE_INVENTORY="$workdir/hosts-bastion" \
    BASTION_ANSIBLE_INVENTORY_ENABLED=0 playbook inventory 2>&1) || true
case "$disabled" in
    *"no bastion host found for this connection"*) ;;
    *)
        echo "the wrapper read the inventory although it is turned off:" >&2
        echo "$disabled" >&2
        exit 1
        ;;
esac

# the inventory of ansible.cfg holds no bastion vars, and neither does any
# other source, the shape reported in issue #4
log "no source of the bastion vars"
missing=$(BASTION_CONF_FILE=/nonexistent playbook no-bastion-host 2>&1) || true
case "$missing" in
    *"no bastion host found for this connection"*) ;;
    *)
        echo "the wrapper did not report the missing bastion host:" >&2
        echo "$missing" >&2
        exit 1
        ;;
esac

log "scp wrapper, bastion vars from the configuration file"
BASTION_CONF_FILE="$workdir/bastion.yml" ANSIBLE_SSH_TRANSFER_METHOD=scp \
    playbook transfer -e transfer=scp-conf -e fetch_dir="$workdir/fetch-scp-conf"

log "scp wrapper, bastion vars from the environment"
(
    export BASTION_USER="$account"
    export BASTION_HOST=127.0.0.1
    export BASTION_PORT="$bastion_port"
    BASTION_CONF_FILE=/nonexistent ANSIBLE_SSH_TRANSFER_METHOD=scp \
        playbook transfer -e transfer=scp-env -e fetch_dir="$workdir/fetch-scp-env"
)

log "sftp wrapper, bastion vars from the configuration file"
BASTION_CONF_FILE="$workdir/bastion.yml" ANSIBLE_SSH_TRANSFER_METHOD=sftp \
    playbook transfer -e transfer=sftp-conf -e fetch_dir="$workdir/fetch-sftp-conf"

log "sftp wrapper, bastion vars from the environment"
(
    export BASTION_USER="$account"
    export BASTION_HOST=127.0.0.1
    export BASTION_PORT="$bastion_port"
    BASTION_CONF_FILE=/nonexistent ANSIBLE_SSH_TRANSFER_METHOD=sftp \
        playbook transfer -e transfer=sftp-env -e fetch_dir="$workdir/fetch-sftp-env"
)

# the sftp hop rides the control master the ssh wrapper opened for the same
# play, and never authenticates on its own, which hides the ssh options the
# wrapper has to forward, the identity file first
log "sftp wrapper without a shared control master"
(
    export ANSIBLE_SSH_ARGS="-C -o UserKnownHostsFile=/dev/null"
    BASTION_CONF_FILE="$workdir/bastion.yml" ANSIBLE_SSH_TRANSFER_METHOD=sftp \
        playbook transfer -e transfer=sftp-no-master \
        -e fetch_dir="$workdir/fetch-sftp-no-master"
)

# the bastion vars exist nowhere the wrapper can look them up, they are computed
# by the play and handed over as ssh options, which is the only channel reaching
# an sftp subsystem invocation and ansible's own temporary directory command.
# Every hop runs on its own, so the transfer wrapper has to resolve the bastion
# rather than ride the master the ssh wrapper opened. Issue #30.
for method in sftp scp; do
    log "$method transfer, bastion vars computed at runtime and passed as ssh options"
    (
        export ANSIBLE_SSH_ARGS="-C -o UserKnownHostsFile=/dev/null"
        BASTION_CONF_FILE=/nonexistent ANSIBLE_SSH_TRANSFER_METHOD="$method" \
            playbook ssh-options -e transfer="$method" \
            -e seed_user="$account" -e seed_host=127.0.0.1 \
            -e seed_port="$bastion_port" \
            -e fetch_dir="$workdir/fetch-ssh-options-$method"
    )
done

# ansible sends no `environment` block with the command creating the temporary
# directory a module is copied into, so the ssh options are the only source
# answering that hop, which pipelining otherwise skips
log "bastion vars as ssh options, without pipelining"
(
    export ANSIBLE_SSH_ARGS="-C -o UserKnownHostsFile=/dev/null"
    export ANSIBLE_PIPELINING=False
    BASTION_CONF_FILE=/nonexistent ANSIBLE_SSH_TRANSFER_METHOD=sftp \
        playbook ssh-options -e transfer=no-pipelining \
        -e seed_user="$account" -e seed_host=127.0.0.1 \
        -e seed_port="$bastion_port" \
        -e fetch_dir="$workdir/fetch-ssh-options-no-pipelining"
)

# the ssh options are the only source holding the bastion vars here, turning
# them off has to fail rather than read them anyway, and the options still have
# to be dropped rather than handed over to an ssh that knows no such name
log "ssh options source turned off"
disabled=$(BASTION_CONF_FILE=/nonexistent BASTION_SSH_OPTIONS_ENABLED=0 \
    playbook ssh-options -e transfer=disabled \
    -e seed_user="$account" -e seed_host=127.0.0.1 \
    -e seed_port="$bastion_port" \
    -e fetch_dir="$workdir/fetch-ssh-options-disabled" 2>&1) || true
case "$disabled" in
    *"Bad configuration option"*)
        echo "the wrapper handed its own ssh options over to ssh:" >&2
        echo "$disabled" | grep "Bad configuration option" >&2
        exit 1
        ;;
    *"no bastion host found for this connection"*) ;;
    *)
        echo "the wrapper read the ssh options although they are turned off:" >&2
        echo "$disabled" >&2
        exit 1
        ;;
esac

# ansible tries sftp, then scp, then a piped dd when the transfer method is
# left at its default, and warns on each one it falls back from rather than
# failing the play. A broken transfer path is invisible here, every task only
# carries a warning and the files travel over the piped dd, the shape reported
# in issue #21. Forcing a method above turns that warning into an error, so
# this is the only scenario that can see it.
log "default transfer method, no mechanism falling back"
smart=$(BASTION_CONF_FILE="$workdir/bastion.yml" \
    playbook transfer -e transfer=smart \
    -e fetch_dir="$workdir/fetch-smart" 2>&1) || {
    echo "the default transfer method failed the play:" >&2
    echo "$smart" >&2
    exit 1
}
case "$smart" in
    *"transfer mechanism failed"*)
        echo "a transfer mechanism fell back to the next one:" >&2
        echo "$smart" | grep "transfer mechanism failed" >&2
        exit 1
        ;;
esac

# The stock ssh connection plugin hands the wrapper one already quoted command,
# which is the only shape every scenario above produces. Mitogen builds its own
# ssh command line, and its first stage arrives as several argv elements: a
# wrapper joining them on a space hands the target a command its shell re-splits
# on the python source, and the play dies on a syntax error. The raw module is
# the other shape the stock path never produces.
log "mitogen strategy and the raw module"
mitogen_strategy=$(python3 -c 'import ansible_mitogen, os
print(os.path.join(os.path.dirname(ansible_mitogen.__file__), "plugins", "strategy"))') || {
    echo "mitogen is not installed, so this scenario would silently test the" >&2
    echo "stock ssh path instead: pip install -r tests/integration/requirements.txt" >&2
    exit 1
}

# ansible refuses to run at all on a strategy it cannot load, so a play that
# reaches its first task is a play mitogen is driving
mitogen_run=$(BASTION_CONF_FILE="$workdir/bastion.yml" \
    ANSIBLE_STRATEGY_PLUGINS="$mitogen_strategy" \
    ANSIBLE_STRATEGY=mitogen_linear \
    playbook mitogen \
    -e target_user="$remote_user" \
    -e ansible_python_interpreter=/usr/bin/python3 2>&1) || {
    echo "the mitogen scenario failed the play:" >&2
    echo "$mitogen_run" >&2
    exit 1
}

log "all integration tests passed"
