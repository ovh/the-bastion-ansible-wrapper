#!/usr/bin/env python3

import getpass
import os
import sys

from lib import find_executable, get_hostvars, manage_conf_file


def main():
    argv = list(sys.argv[1:])  # Copy

    bastion_user = None
    bastion_host = None
    bastion_port = None
    remote_user = None
    remote_port = 22
    default_configuration_file = "/etc/ovh/bastion/config.yml"

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

    # check if bastion_vars are passed as env vars in the playbook
    # may be usefull if the ansible controller manage many bastions
    for i in list(scpcmd.split(" ")):
        if "bastion_user" in i.lower():
            bastion_user = i.split("=")[1]
        elif "bastion_host" in i.lower():
            bastion_host = i.split("=")[1]
        elif "bastion_port" in i.lower():
            bastion_port = i.split("=")[1]

    # read from configuration file
    if not bastion_host or not bastion_port or not bastion_user:
        bastion_host, bastion_port, bastion_user = manage_conf_file(
            os.getenv("BASTION_CONF_FILE", default_configuration_file),
            bastion_host,
            bastion_port,
            bastion_user,
        )

    # lookup on the inventory may take some time, depending on the source, so use it only if not defined elsewhere
    # it seems like some module like template does not send env vars too...
    if not bastion_host or not bastion_port or not bastion_user:
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
