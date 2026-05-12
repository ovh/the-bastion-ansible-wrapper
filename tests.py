import os

from yaml import dump

import shlex

from lib import (
    awx_get_inventory_file,
    get_bastion_vars,
    get_var_within,
    manage_conf_file,
    parse_ssh_argv,
    shell_wrap_command,
)

BASTION_HOST = "my_bastion"
BASTION_PORT = 22
BASTION_USER = "my_bastion_user"
BASTION_CONF_FILE = "/tmp/test_bastion_conf_file.yml"


def test_manage_conf_file_bastion_host_undefined():
    bastion_host, bastion_port, bastion_user = manage_conf_file(
        BASTION_CONF_FILE, None, BASTION_PORT, BASTION_USER
    )
    assert bastion_host == BASTION_HOST


def test_manage_conf_file_bastion_port_undefined():
    bastion_host, bastion_port, bastion_user = manage_conf_file(
        BASTION_CONF_FILE, BASTION_HOST, None, BASTION_USER
    )
    assert bastion_port == BASTION_PORT


def test_manage_conf_file_bastion_user_undefined():
    bastion_host, bastion_port, bastion_user = manage_conf_file(
        BASTION_CONF_FILE, BASTION_HOST, BASTION_PORT, None
    )
    assert bastion_user == BASTION_USER


def test_manage_conf_file_bastion_all_undefined():
    write_conf_file(BASTION_CONF_FILE)
    bastion_host, bastion_port, bastion_user = manage_conf_file(
        BASTION_CONF_FILE, None, None, None
    )
    assert bastion_user == BASTION_USER
    assert bastion_port == BASTION_PORT
    assert bastion_host == BASTION_HOST


def write_conf_file(conf_file):
    with open(conf_file, "w") as f:

        data = {
            "bastion_host": BASTION_HOST,
            "bastion_port": BASTION_PORT,
            "bastion_user": BASTION_USER,
        }

        dump(data, f)


write_conf_file(BASTION_CONF_FILE)


def test_get_var_within_one_level():
    hostvars = {"bastion_host": "{{ bastion_fqdn }}", "bastion_fqdn": "my_real_bastion"}
    bastion_host = get_var_within(hostvars["bastion_host"], hostvars)
    assert bastion_host == hostvars["bastion_fqdn"]


def test_get_var_within_two_levels():
    hostvars = {
        "bastion_host": "{{ bastion_fqdn }}",
        "bastion_fqdn": "{{ my_other_var }}",
        "my_other_var": "my_real_bastion",
    }
    bastion_host = get_var_within(hostvars["bastion_host"], hostvars)
    assert bastion_host == hostvars["my_other_var"]


def test_get_var_within_not_found():
    hostvars = {"bastion_host": "{{ bastion_fqdn }}"}
    bastion_host = get_var_within(hostvars["bastion_host"], hostvars)
    assert not bastion_host


def test_get_var_within_infinite():
    hostvars = {
        "bastion_host": "{{ bastion_fqdn }}",
        "bastion_fqdn": "{{ bastion_host }}",
    }
    bastion_host = get_var_within(hostvars["bastion_host"], hostvars)
    assert not bastion_host


def test_get_var_not_a_jinja2_var():
    hostvars = {"bastion_host": "{{ bastion_fqdn"}
    bastion_host = get_var_within(hostvars["bastion_host"], hostvars)
    assert bastion_host == hostvars["bastion_host"]


def test_get_var_not_a_string():
    hostvars = {"bastion_host": 68}
    bastion_host = get_var_within(hostvars["bastion_host"], hostvars)
    assert bastion_host == hostvars["bastion_host"]


def test_awx_get_inventory_file_default():
    assert awx_get_inventory_file() == "/runner/inventory/hosts"


def test_awx_get_inventory_file_env_defined():
    env_path = "/my_awx"
    os.environ["AWX_RUN_DIR"] = env_path
    assert awx_get_inventory_file() == f"{env_path}/inventory/hosts"
    os.environ.pop("AWX_RUN_DIR")


def test_get_bastion_vars():
    host_vars = {
        "bastion_port": BASTION_PORT,
        "bastion_host": BASTION_HOST,
        "bastion_user": BASTION_USER,
    }
    bastion_vars = get_bastion_vars(host_vars)
    assert (
        bastion_vars["bastion_port"] == BASTION_PORT
        and bastion_vars["bastion_host"] == BASTION_HOST
        and bastion_vars["bastion_user"] == BASTION_USER
    )


def test_get_bastion_vars_not_full():
    host_vars = {"bastion_port": BASTION_PORT, "bastion_user": BASTION_USER}
    bastion_vars = get_bastion_vars(host_vars)
    assert not bastion_vars["bastion_host"]


def test_parse_ssh_argv_standard_ansible_layout():
    # Standard Ansible ssh plugin: opts use -o Key=Value pairs, the command is
    # a single shell-quoted string, and the host sits between them.
    argv = [
        "-C",
        "-o", "ControlMaster=auto",
        "-o", "User=root",
        "-o", "Port=22",
        "my-target-host.example.com",
        "/bin/sh -c '/usr/bin/python3 && sleep 0'",
    ]
    options, host, remote_commands_parts = parse_ssh_argv(argv)
    assert host == "my-target-host.example.com"
    assert remote_commands_parts == ["/bin/sh -c '/usr/bin/python3 && sleep 0'"]
    assert options == [
        "-C",
        "-o", "ControlMaster=auto",
        "-o", "User=root",
        "-o", "Port=22",
    ]


def test_parse_ssh_argv_mitogen_layout():
    # Mitogen passes the remote python bootstrap as multiple argv elements
    # (python, -c, <code>, <base64>, <controller>, <pid>) and uses -l/-p
    # short flags rather than -o User=/-o Port=.
    argv = [
        "-o", "LogLevel ERROR",
        "-l", "root",
        "-o", "ControlMaster=auto",
        "-C",
        "2a06:c480:666:136::12",
        "python3.12",
        "-c",
        "'import sys;exec()'",
        "base64payload==",
        "controller.local:12345",
        "19148",
    ]
    options, host, remote_commands_parts = parse_ssh_argv(argv)
    assert host == "2a06:c480:666:136::12"
    assert remote_commands_parts == [
        "python3.12",
        "-c",
        "'import sys;exec()'",
        "base64payload==",
        "controller.local:12345",
        "19148",
    ]
    assert options == [
        "-o", "LogLevel ERROR",
        "-l", "root",
        "-o", "ControlMaster=auto",
        "-C",
    ]


def test_parse_ssh_argv_double_dash_delimiter():
    # The "--" sentinel forces option parsing to stop; the next element is
    # the host and everything after is the command.
    argv = ["-C", "--", "host.example.com", "uptime"]
    options, host, remote_commands_parts = parse_ssh_argv(argv)
    assert host == "host.example.com"
    assert remote_commands_parts == ["uptime"]
    assert options == ["-C", "--"]


def test_parse_ssh_argv_no_host():
    # Only options, no positional: host must be None and cmd parts empty.
    argv = ["-C", "-o", "BatchMode=yes"]
    options, host, remote_commands_parts = parse_ssh_argv(argv)
    assert host is None
    assert remote_commands_parts == []
    assert options == ["-C", "-o", "BatchMode=yes"]


def test_parse_ssh_argv_empty():
    options, host, remote_commands_parts = parse_ssh_argv([])
    assert host is None
    assert remote_commands_parts == []
    assert options == []


def test_parse_ssh_argv_option_consumes_next_arg():
    # Single-letter flags that take an argument (-l, -p, -i, -o, ...) must
    # consume the following element, even when its value would otherwise look
    # like a positional (e.g. a bare hostname-shaped string).
    argv = ["-l", "host-shaped-user", "real-host", "uptime"]
    options, host, remote_commands_parts = parse_ssh_argv(argv)
    assert host == "real-host"
    assert remote_commands_parts == ["uptime"]
    assert options == ["-l", "host-shaped-user"]


def test_parse_ssh_argv_combined_short_flag():
    # Combined short flag with inline value (-lroot, -p22) must not consume
    # the next argv element.
    argv = ["-lroot", "-p22", "host.example.com", "uptime"]
    options, host, remote_commands_parts = parse_ssh_argv(argv)
    assert host == "host.example.com"
    assert remote_commands_parts == ["uptime"]
    assert options == ["-lroot", "-p22"]


def test_shell_wrap_command_empty():
    assert shell_wrap_command([]) == ""


def test_shell_wrap_command_passthrough_when_already_shell():
    # Standard Ansible ssh plugin already wraps the command in ``/bin/sh -c``;
    # the wrapper must leave it untouched (no double-wrap).
    parts = ["/bin/sh -c '/usr/bin/python3 && sleep 0'"]
    assert shell_wrap_command(parts) == parts[0]


def test_shell_wrap_command_wraps_mitogen_layout():
    # Mitogen emits the bootstrap as multiple argv elements without any
    # ``/bin/sh`` wrapper: we must shell-quote and wrap them so the bastion
    # receives a single, safe cmd string.
    parts = ["python3.12", "-c", "'import sys; exec()'", "payload=="]
    wrapped = shell_wrap_command(parts)
    assert wrapped.startswith("/bin/sh -c ")
    # The quoted payload must round-trip through shlex.split back to the
    # original (space-joined) command.
    assert shlex.split(wrapped[len("/bin/sh -c "):]) == [" ".join(parts)]
