#! /usr/bin/env python

import getpass
import os
import sys

from lib import find_executable, get_hostvars


def main():
    argv = list(sys.argv[1:])  # Copy

    remote_user = None
    remote_port = 22

    cmd = argv.pop()
    host = argv.pop()
    hostvar = get_hostvars(host)  # dict

    bastion_port = hostvar.get("bastion_port", os.environ.get("BASTION_PORT", 22))
    bastion_user = hostvar.get(
        "bastion_user", os.environ.get("BASTION_USER", getpass.getuser())
    )
    bastion_host = hostvar.get("bastion_host", os.environ.get("BASTION_HOST"))

    for i, e in enumerate(argv):

        if e.startswith("User="):
            remote_user = e.split("=")[-1]
            argv[i] = "User={}".format(bastion_user)
        elif e.startswith("Port="):
            remote_port = e.split("=")[-1]
            argv[i] = "Port={}".format(bastion_port)

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
            "-t",
        ]
        + argv
        + [
            "--",
            "-q",
            "--never-escape",
            "--user",
            remote_user,
            "--port",
            remote_port,
            host,
            "--",
            cmd,
        ]
    )
    os.execv(
        find_executable("ssh"),  # full path mandatory
        [str(e).strip() for e in args],  # execv() arg 2 must contain only strings
    )


if __name__ == "__main__":
    main()
