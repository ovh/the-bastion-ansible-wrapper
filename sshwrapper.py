#!/usr/bin/env python3

import getpass
import os
import sys

from lib import (
    awx_get_inventory_file,
    awx_get_vars,
    find_executable,
    get_hostvars,
    get_var_within,
    manage_conf_file,
    parse_ssh_argv,
    shell_wrap_command,
)


def main():
    bastion_user = None
    bastion_host = None
    bastion_port = None
    remote_user = None
    remote_port = 22
    default_configuration_file = "/etc/ovh/bastion/config.yml"

    argv, host, remote_commands_parts = parse_ssh_argv(sys.argv[1:])
    if host is None:
        sys.stderr.write("sshwrapper: no host found in argv\n")
        sys.exit(1)

    # Normalize the remote command into a single shell-safe string. The
    # standard Ansible ssh plugin already emits one ``/bin/sh -c '...'``
    # element; Mitogen emits several (``python``, ``-c``, ``<code>``, ...)
    # that we wrap via /bin/sh -c with proper shell-quoting.
    remote_commands = shell_wrap_command(remote_commands_parts)

    # check if bastion_vars are passed as env vars in the playbook
    # may be usefull if the ansible controller manage many bastions
    # example :
    # - hosts: all
    #   gather_facts: false
    #   environment:
    #     BASTION_USER: "{{ bastion_user }}"
    #     BASTION_HOST: "{{ bastion_host }}"
    #     BASTION_PORT: "{{ bastion_port }}"
    #
    # will result as : ... '/bin/sh -c '"'"'BASTION_USER=my_bastion_user BASTION_HOST=my_bastion_host BASTION_PORT=22 /usr/bin/python3 && sleep 0'"'"''
    for i in list(remote_commands.split(" ")):
        if "bastion_user" in i.lower():
            bastion_user = i.split("=")[1]
        elif "bastion_host" in i.lower():
            bastion_host = i.split("=")[1]
        elif "bastion_port" in i.lower():
            bastion_port = i.split("=")[1]

    # in some cases (AWX in a non containerised environment for instance), the environment is overridden by the job
    # so we are not able to get the BASTION vars
    # if some vars are still undefined, try to load them from a configuration file
    if not bastion_host or not bastion_port or not bastion_user:
        bastion_host, bastion_port, bastion_user = manage_conf_file(
            os.environ.get("BASTION_CONF_FILE", default_configuration_file),
            bastion_host,
            bastion_port,
            bastion_user,
        )

    # lookup on the inventory may take some time, depending on the source, so use it only if not defined elsewhere
    # it seems like some module like template does not send env vars too...
    if not bastion_host or not bastion_port or not bastion_user:

        # check if running on AWX, we'll get the vars in a different way
        awx_inventory_file = awx_get_inventory_file()
        if os.path.exists(awx_inventory_file):
            hostvar = awx_get_vars(host, awx_inventory_file)
        else:
            hostvar = get_hostvars(host)  # dict

        # manage the case where a bastion var is defined from another var
        # Ex: bastion_host = {{ my_bastion_host }}
        bastion_port = get_var_within(
            hostvar.get("bastion_port", os.environ.get("BASTION_PORT", 22)), hostvar
        )
        bastion_user = get_var_within(
            hostvar.get(
                "bastion_user", os.environ.get("BASTION_USER", getpass.getuser())
            ),
            hostvar,
        )
        bastion_host = get_var_within(
            hostvar.get("bastion_host", os.environ.get("BASTION_HOST")), hostvar
        )

    # Extract the remote user/port from the parsed options and rewrite those
    # flags to point at the bastion so the outer ``ssh`` connects there; the
    # original target values are forwarded to the bastion via ``--user`` /
    # ``--port`` below. Handles both Ansible's standard ssh plugin format
    # (``-o User=X`` / ``-o Port=X``) and the short form used by other plugins
    # (``-l X`` / ``-p X``, e.g. Mitogen).
    i = 0
    while i < len(argv):
        e = argv[i]
        if e == "-l" and i + 1 < len(argv):
            remote_user = argv[i + 1]
            argv[i + 1] = bastion_user
            i += 2
        elif e == "-p" and i + 1 < len(argv):
            remote_port = argv[i + 1]
            argv[i + 1] = bastion_port
            i += 2
        elif e.startswith("User="):
            remote_user = e.split("=")[-1]
            argv[i] = "User={}".format(bastion_user)
            i += 1
        elif e.startswith("Port="):
            remote_port = e.split("=")[-1]
            argv[i] = "Port={}".format(bastion_port)
            i += 1
        else:
            i += 1

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
        + argv
        + [
            "--",
            "-q",
            "-T",
            "--never-escape",
            "--user",
            remote_user,
            "--port",
            remote_port,
            host,
            "--",
            remote_commands,
        ]
    )
    os.execv(
        find_executable("ssh"),  # full path mandatory
        [str(e).strip() for e in args],  # execv() arg 2 must contain only strings
    )


if __name__ == "__main__":
    main()
