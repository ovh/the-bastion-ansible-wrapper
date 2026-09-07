#!/usr/bin/env python3

import os
import sys

from lib import (
    awx_get_inventory_file,
    awx_get_vars,
    check_bastion_host,
    fill_bastion_vars,
    find_executable,
    get_hostvars,
    has_remote_command,
    manage_conf_file,
    parse_bastion_env_vars,
    parse_bastion_ssh_options,
    parse_ssh_argv,
    source_enabled,
)


def main():
    argv = list(sys.argv[1:])  # Copy

    remote_user = None
    remote_port = 22
    default_configuration_file = "/etc/ovh/bastion/config.yml"

    ssh = find_executable("ssh")
    if not ssh:
        sys.exit("bastion wrapper: no ssh executable found in PATH")

    # ansible renders `ansible_ssh_common_args` from the hostvars of the moment,
    # a set_fact included, and appends it to every wrapper it runs
    bastion_host, bastion_port, bastion_user, argv = parse_bastion_ssh_options(argv)
    if not source_enabled("BASTION_SSH_OPTIONS_ENABLED"):
        bastion_host = bastion_port = bastion_user = None

    # nothing to proxy, hand the arguments over to ssh untouched
    if not has_remote_command(argv):
        os.execv(ssh, ["ssh"] + argv)

    options, _, remaining = parse_ssh_argv(argv)
    host = remaining[0]
    # ssh joins the arguments following the host with a space and sends that
    # string, quoting none of them, so a connection plugin handing over several
    # quotes them itself: mitogen shlex-quotes every element of its boot
    # command. Quoting them here again would reach python as its own quotes.
    cmd = " ".join(remaining[1:])

    # check if bastion_vars are passed as env vars in the playbook
    # may be usefull if the ansible controller manage many bastions
    # example :
    # - hosts: all
    #   gather_facts: false
    #   environment:
    #     BASTION_USER: "{{ bastion_user }}"
    #     BASTION_HOST: "{{ bastion_host }}"
    #     BASTION_PORT: "{{ bastion_port }}"
    if (not bastion_host or not bastion_port or not bastion_user) and source_enabled(
        "BASTION_PLAYBOOK_ENV_ENABLED"
    ):
        env_host, env_port, env_user = parse_bastion_env_vars(cmd)
        bastion_host = bastion_host or env_host
        bastion_port = bastion_port or env_port
        bastion_user = bastion_user or env_user

    # in some cases (AWX in a non containerised environment for instance), the environment is overridden by the job
    # so we are not able to get the BASTION vars
    # if some vars are still undefined, try to load them from a configuration file
    if (not bastion_host or not bastion_port or not bastion_user) and source_enabled(
        "BASTION_CONF_FILE_ENABLED"
    ):
        bastion_host, bastion_port, bastion_user = manage_conf_file(
            os.environ.get("BASTION_CONF_FILE", default_configuration_file),
            bastion_host,
            bastion_port,
            bastion_user,
        )

    # lookup on the inventory may take some time, depending on the source, so use it only if not defined elsewhere
    # it seems like some module like template does not send env vars too...
    if not bastion_host or not bastion_port or not bastion_user:
        hostvar = {}

        if source_enabled("BASTION_ANSIBLE_INVENTORY_ENABLED"):
            # check if running on AWX, we'll get the vars in a different way
            awx_inventory_file = awx_get_inventory_file()
            if os.path.exists(awx_inventory_file):
                hostvar = awx_get_vars(host, awx_inventory_file)
            else:
                hostvar = get_hostvars(host)  # dict

        bastion_host, bastion_port, bastion_user = fill_bastion_vars(
            hostvar, bastion_host, bastion_port, bastion_user
        )

    check_bastion_host(bastion_host)

    # a connection plugin names the remote user and port with either form,
    # and the bastion is what the connection actually opens, so its own answer
    # replaces them wherever they are found
    for i, e in enumerate(options):

        if e.startswith("User="):
            remote_user = e.split("=")[-1]
            options[i] = "User={}".format(bastion_user)
        elif e.startswith("Port="):
            remote_port = e.split("=")[-1]
            options[i] = "Port={}".format(bastion_port)
        elif e == "-l" and i + 1 < len(options):
            remote_user = options[i + 1]
            options[i + 1] = str(bastion_user)
        elif e == "-p" and i + 1 < len(options):
            remote_port = options[i + 1]
            options[i + 1] = str(bastion_port)

    # a connection plugin naming no remote user leaves the bastion to pick its
    # own default, which passing the word None would take away from it
    remote = ["--user", remote_user] if remote_user else []
    remote += ["--port", remote_port]

    # syscall exec
    args = (
        [
            "ssh",
            "-p",
            bastion_port,
            "-q",
            "-o",
            "StrictHostKeyChecking=no",
            "-l",
            bastion_user,
            bastion_host,
            "-T",
        ]
        + options
        + ["--", "-q", "-T", "--never-escape"]
        + remote
        + [
            host,
            "--",
            cmd,
        ]
    )
    os.execv(
        ssh,
        [str(e).strip() for e in args],  # execv() arg 2 must contain only strings
    )


if __name__ == "__main__":
    main()
