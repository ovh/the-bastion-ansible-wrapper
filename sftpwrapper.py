#!/usr/bin/env python3

import os
import sys

from lib import (
    check_bastion_host,
    fill_bastion_vars,
    find_executable,
    get_hostvars,
    manage_conf_file,
    parse_bastion_ssh_options,
    source_enabled,
)


def main():
    argv = list(sys.argv[1:])

    remote_user = None
    remote_port = 22
    default_configuration_file = "/etc/ovh/bastion/config.yml"

    ssh = find_executable("ssh")
    if not ssh:
        sys.exit("bastion wrapper: no ssh executable found in PATH")

    if len(argv) < 2:
        sys.exit("bastion wrapper: no host to proxy")

    # sftp asks for a subsystem and sends no command, so a playbook `environment`
    # block has nothing to be inlined into and never reaches here. Ansible
    # renders `ansible_ssh_common_args` from the hostvars of the moment, a
    # set_fact included, and appends it to the command line below, which is the
    # only channel left for a var known at runtime only.
    bastion_host, bastion_port, bastion_user, argv = parse_bastion_ssh_options(argv)
    if not source_enabled("BASTION_SSH_OPTIONS_ENABLED"):
        bastion_host = bastion_port = bastion_user = None

    # sftp ends its arguments with the host and the subsystem it asks for
    host = argv[-2]

    iteration = enumerate(argv)
    sshcmdline = []
    for i, e in iteration:
        # a trailing option has no value, and reading one raises
        value = argv[i + 1] if i + 1 < len(argv) else ""
        if e == "-o" and value.startswith("User="):
            remote_user = value.split("=")[-1]
            next(iteration)
        elif e == "-o" and value.startswith("Port="):
            remote_port = value.split("=")[-1]
            next(iteration)
        elif e in ("-s", "--"):
            # osh is a command, not an ssh subsystem
            break
        else:
            sshcmdline.append(e)

    # Read from configuration file
    if (not bastion_host or not bastion_port or not bastion_user) and source_enabled(
        "BASTION_CONF_FILE_ENABLED"
    ):
        bastion_host, bastion_port, bastion_user = manage_conf_file(
            os.getenv("BASTION_CONF_FILE", default_configuration_file),
            bastion_host,
            bastion_port,
            bastion_user,
        )

    # Read from inventory and environment variables
    if not bastion_host or not bastion_port or not bastion_user:
        hostvar = {}
        if source_enabled("BASTION_ANSIBLE_INVENTORY_ENABLED"):
            hostvar = get_hostvars(host)

        bastion_host, bastion_port, bastion_user = fill_bastion_vars(
            hostvar, bastion_host, bastion_port, bastion_user
        )

    check_bastion_host(bastion_host)

    # ansible passes the identity file and its ssh options to sftp, which hands
    # them over here, and the bastion connection needs them
    args = (
        [
            "ssh",
            "{}@{}".format(bastion_user, bastion_host),
            "-p",
            bastion_port,
            "-o",
            "StrictHostKeyChecking=no",
            "-T",
        ]
        + sshcmdline
        + [
            "--",
            "--user",
            remote_user,
            "--port",
            remote_port,
            "--host",
            host,
            "--osh",
            "sftp",
        ]
    )

    os.execv(
        ssh,
        [str(e).strip() for e in args],
    )


if __name__ == "__main__":
    main()
