#!/usr/bin/env python3

import getpass
import os
import sys

from lib import find_executable, get_hostvars, manage_conf_file


def main():
    argv = list(sys.argv[1:])

    bastion_user = None
    bastion_host = None
    bastion_port = None
    remote_user = None
    remote_port = 22
    default_configuration_file = "/etc/ovh/bastion/config.yml"

    iteration = enumerate(argv)
    for i, e in iteration:
        if e == "-o" and argv[i + 1].startswith("User="):
            remote_user = argv[i + 1].split("=")[-1]
            next(iteration)
        elif e == "-o" and argv[i + 1].startswith("Port="):
            remote_port = argv[i + 1].split("=")[-1]
            next(iteration)

    sftpcmd = argv.pop()
    host = argv.pop()

    # Playbook environment variables are not pushed to the sftp wrapper
    # Skipping this source of configuration

    # Read from configuration file
    bastion_host, bastion_port, bastion_user = manage_conf_file(
        os.getenv("BASTION_CONF_FILE", default_configuration_file),
        bastion_host,
        bastion_port,
        bastion_user,
    )

    # Read from inventory and environment variables
    if not bastion_host or not bastion_port or not bastion_user:
        inventory = get_hostvars(host)
        bastion_port = inventory.get("bastion_port", os.getenv("BASTION_PORT", 22))
        bastion_user = inventory.get(
            "bastion_user", os.getenv("BASTION_USER", getpass.getuser())
        )
        bastion_host = inventory.get("bastion_host", os.getenv("BASTION_HOST"))

    args = [
        "ssh",
        "{}@{}".format(bastion_user, bastion_host),
        "-p",
        bastion_port,
        "-o",
        "StrictHostKeyChecking=no",
        "-T",
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

    os.execv(
        find_executable("ssh"),
        [str(e).strip() for e in args],
    )


if __name__ == "__main__":
    main()
