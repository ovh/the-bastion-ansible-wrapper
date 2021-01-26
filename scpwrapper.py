#! /usr/bin/env python

import getpass
import os
import sys

from lib import find_executable, get_hostvars


def main():
    argv = list(sys.argv[1:])  # Copy

    remote_user = None
    remote_port = 22

    iteration = enumerate(argv)
    sshcmdline = []
    for i, e in iteration:
        if e == "-l":
            remote_user = argv[i + 1]
            next(iteration)
        elif e == "-p":
            remote_port = argv[i + 1]
            next(iteration)
        elif e == "-o" and argv[i + 1].startswith("User="):
            remote_user = argv[i + 1].split("=")[-1]
            next(iteration)
        elif e == "-o" and argv[i + 1].startswith("Port="):
            remote_port = argv[i + 1].split("=")[-1]
            next(iteration)
        elif e == "--":
            sshcmdline.extend(argv[i + 1 :])
            break
        else:
            sshcmdline.append(e)

    scpcmd = sshcmdline.pop()
    host = sshcmdline.pop()
    scpcmd = scpcmd.replace("#", "##").replace(" ", "#")

    hostvar = get_hostvars(host)  # dict

    bastion_port = hostvar.get("bastion_port", os.environ.get("BASTION_PORT", 22))
    bastion_user = hostvar.get(
        "bastion_user", os.environ.get("BASTION_USER", getpass.getuser())
    )
    bastion_host = hostvar.get("bastion_host", os.environ.get("BASTION_HOST"))

    # syscall exec
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
            "scp",
            "--scp-cmd",
            scpcmd,
        ]
    )

    os.execv(
        find_executable("ssh"),  # absolute path mandatory
        [str(e).strip() for e in args],  # execv() arg 2 must contain only strings
    )


if __name__ == "__main__":
    main()
