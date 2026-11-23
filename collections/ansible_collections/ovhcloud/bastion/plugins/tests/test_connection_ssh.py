"""Unit tests for bastion connection plugin (plugins/connection/ssh.py)"""

import shlex

import pytest
import yaml

# Skip all tests if ansible is not installed
pytest.importorskip("ansible")

import ansible.constants as C
from ansible.plugins.connection.ssh import DOCUMENTATION as SSH_DOCUMENTATION

from connection import ssh as bastion_ssh

BASTION_OPTIONS = ("bastion_host", "bastion_port", "bastion_user", "bastion_ssh_options")
PLUGIN_NAME = "ovhcloud.bastion.ssh"

# what the plugin loader does when loading the plugin
C.config.initialize_plugin_configuration_definitions(
    "connection", PLUGIN_NAME, yaml.safe_load(bastion_ssh.DOCUMENTATION)["options"]
)


def make_connection(connection_class=None, **options):
    """
    Create a Connection instance without calling its __init__.
    Options are pre-filled, as Ansible would do through set_options().
    """
    connection_class = connection_class or bastion_ssh.Connection
    conn = connection_class.__new__(connection_class)
    conn._load_name = PLUGIN_NAME
    conn._origins = {}
    conn._options = {
        "bastion_host": "bastion.example.com",
        "bastion_port": 2222,
        "bastion_user": "bastion_user",
        "bastion_ssh_options": "-q -T --never-escape",
        "remote_user": "root",
        "port": 2200,
    }
    conn._options.update(options)
    return conn


@pytest.fixture(autouse=True)
def clean_bastion_env(monkeypatch):
    """Make sure BASTION_* variables from the developer environment do not leak into the tests."""
    for option in BASTION_OPTIONS:
        monkeypatch.delenv(option.upper(), raising=False)


@pytest.fixture
def super_build(monkeypatch):
    """Replace SSHConnection._build_command and record its calls, with the options seen at call time."""
    calls = []

    def fake_build(self, binary, subsystem, *other_args):
        calls.append(
            {
                "subsystem": subsystem,
                "args": list(other_args),
                "port": self.get_option("port"),
                "user": self.get_option("remote_user"),
            }
        )
        return [binary, *other_args]

    monkeypatch.setattr(bastion_ssh.SSHConnection, "_build_command", fake_build)
    return calls


# Tests for DOCUMENTATION


def test_documentation_keeps_ssh_options():
    """DOCUMENTATION extends the ssh connection plugin options."""
    doc = yaml.safe_load(bastion_ssh.DOCUMENTATION)
    ssh_doc = yaml.safe_load(SSH_DOCUMENTATION)

    assert set(ssh_doc["options"]) <= set(doc["options"])


@pytest.mark.parametrize("option", BASTION_OPTIONS)
def test_documentation_declares_bastion_option_sources(option):
    """Bastion options can be set from host / group vars and ansible.cfg (env is handled by the plugin)."""
    definition = yaml.safe_load(bastion_ssh.DOCUMENTATION)["options"][option]

    assert definition["vars"] == [{"name": option}]
    assert definition["ini"] == [{"section": "ovh", "key": option}]
    assert "env" not in definition


def test_bastion_options_are_resolved_by_ansible_config():
    """Ansible exposes the bastion host / group vars to the plugin."""
    # the TaskExecutor only templates and passes the vars listed here
    assert set(BASTION_OPTIONS) <= set(C.config.get_plugin_vars("connection", PLUGIN_NAME))

    value = C.config.get_config_value(
        "bastion_host",
        plugin_type="connection",
        plugin_name=PLUGIN_NAME,
        variables={"bastion_host": "hv-bastion.example.com"},
    )
    assert value == "hv-bastion.example.com"


# Tests for _get_bastion_option


@pytest.mark.parametrize("option", BASTION_OPTIONS)
def test_get_bastion_option_env_overrides_vars(monkeypatch, option):
    """Environment variables take precedence over host / group vars and ansible.cfg."""
    monkeypatch.setenv(option.upper(), "from-env")
    conn = make_connection(**{option: "from-vars"})

    assert conn._get_bastion_option(option) == "from-env"


def test_get_bastion_option_falls_back_to_plugin_option(monkeypatch):
    """Without environment variable, the option resolved by Ansible (vars > ini > default) is used."""
    monkeypatch.delenv("BASTION_HOST", raising=False)
    conn = make_connection(bastion_host="from-vars")

    assert conn._get_bastion_option("bastion_host") == "from-vars"


def test_build_command_uses_env_bastion(monkeypatch, super_build):
    """Environment variables are used to build the bastion command."""
    monkeypatch.setenv("BASTION_HOST", "env-bastion.example.com")
    monkeypatch.setenv("BASTION_PORT", "2022")
    monkeypatch.setenv("BASTION_USER", "env_user")
    conn = make_connection()
    conn._through_bastion = True

    conn._build_command("ssh", "ssh", "target.example.com", "id")

    assert super_build[0]["args"][0] == "env-bastion.example.com"
    assert super_build[0]["port"] == 2022
    assert super_build[0]["user"] == "env_user"


# Tests for _build_command


def test_build_command_goes_through_bastion(super_build):
    """The target is moved after the bastion, and ssh connects to the bastion."""
    conn = make_connection()
    conn._through_bastion = True

    conn._build_command("ssh", "ssh", "-tt", "target.example.com", "id")

    assert super_build == [
        {
            "subsystem": "ssh",
            "args": [
                "-tt",
                "bastion.example.com",
                "--",
                "-q",
                "-T",
                "--never-escape",
                "--user",
                "root",
                "--port",
                "2200",
                "target.example.com",
                "--",
                "id",
            ],
            "port": 2222,
            "user": "bastion_user",
        }
    ]


def test_build_command_keeps_remote_command_as_single_argument(super_build):
    """The remote command is not split, spaces and newlines are preserved."""
    conn = make_connection()
    conn._through_bastion = True
    remote_cmd = "/bin/sh -c 'echo  \"a b\"\necho c'"

    conn._build_command("ssh", "ssh", "target.example.com", remote_cmd)

    assert super_build[0]["args"][-1] == remote_cmd


def test_build_command_uses_custom_bastion_ssh_options(super_build):
    """bastion_ssh_options are split like a shell would."""
    conn = make_connection(bastion_ssh_options="-q --opt 'a b'")
    conn._through_bastion = True

    conn._build_command("ssh", "ssh", "target.example.com", "id")

    assert super_build[0]["args"][1:5] == ["--", "-q", "--opt", "a b"]


def test_build_command_defaults_target_port_to_22(super_build):
    """Target port defaults to 22 when not set."""
    conn = make_connection(port=None)
    conn._through_bastion = True

    conn._build_command("ssh", "ssh", "target.example.com", "id")

    args = super_build[0]["args"]
    assert args[args.index("--port") + 1] == "22"


def test_build_command_restores_target_options(super_build):
    """Target user and port options are restored once the command is built."""
    conn = make_connection()
    conn._through_bastion = True

    conn._build_command("ssh", "ssh", "target.example.com", "id")

    assert conn.get_option("port") == 2200
    assert conn.get_option("remote_user") == "root"


def test_build_command_restores_target_options_on_error(monkeypatch):
    """Target user and port options are restored even if the parent build fails."""

    def failing_build(self, binary, subsystem, *other_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(bastion_ssh.SSHConnection, "_build_command", failing_build)
    conn = make_connection()
    conn._through_bastion = True

    with pytest.raises(RuntimeError):
        conn._build_command("ssh", "ssh", "target.example.com", "id")

    assert conn.get_option("port") == 2200
    assert conn.get_option("remote_user") == "root"


def test_build_command_untouched_outside_exec_command(super_build):
    """Commands not built by exec_command (ex: 'ssh -O stop' on reset) are not rewritten."""
    conn = make_connection()

    conn._build_command("ssh", "ssh", "-O", "stop", "target.example.com")

    assert super_build[0]["args"] == ["-O", "stop", "target.example.com"]
    assert super_build[0]["port"] == 2200
    assert super_build[0]["user"] == "root"


def test_build_command_untouched_for_other_subsystems(super_build):
    """sftp commands are not rewritten."""
    conn = make_connection()
    conn._through_bastion = True

    conn._build_command("sftp", "sftp", "target.example.com")

    assert super_build[0]["args"] == ["target.example.com"]


@pytest.mark.parametrize("option", ["bastion_host", "bastion_user", "remote_user"])
def test_build_command_raises_when_option_missing(super_build, option):
    """A clear error is raised when a mandatory value is missing."""
    conn = make_connection(**{option: None})
    conn._through_bastion = True

    with pytest.raises(bastion_ssh.AnsibleConnectionFailure, match=option):
        conn._build_command("ssh", "ssh", "target.example.com", "id")

    assert super_build == []


# Tests for exec_command


def test_exec_command_enables_bastion_only_during_call(monkeypatch):
    """exec_command enables the bastion rewrite only while the parent exec_command runs."""
    seen = []

    def fake_exec(self, cmd, in_data=None, sudoable=True):
        seen.append((self._through_bastion, cmd, in_data, sudoable))
        return 0, b"ok", b""

    monkeypatch.setattr(bastion_ssh.SSHConnection, "exec_command", fake_exec)
    conn = make_connection()

    result = conn.exec_command("id", in_data=b"data", sudoable=False)

    assert result == (0, b"ok", b"")
    assert seen == [(True, "id", b"data", False)]
    assert conn._through_bastion is False


def test_exec_command_disables_bastion_on_error(monkeypatch):
    """The bastion rewrite is disabled even if the parent exec_command fails."""

    def failing_exec(self, cmd, in_data=None, sudoable=True):
        raise bastion_ssh.AnsibleConnectionFailure("boom")

    monkeypatch.setattr(bastion_ssh.SSHConnection, "exec_command", failing_exec)
    conn = make_connection()

    with pytest.raises(bastion_ssh.AnsibleConnectionFailure):
        conn.exec_command("id")

    assert conn._through_bastion is False


# Tests for file transfers


class FakeShell:
    @staticmethod
    def quote(path):
        return shlex.quote(path)


@pytest.fixture
def scp_run(monkeypatch, super_build):
    """Replace SSHConnection._run: record the command and stdin, and answer with the configured rc / stdout."""
    runs = {"rc": 0, "stdout": b"", "calls": []}

    def fake_run(self, cmd, in_data, sudoable=True, checkrc=True):
        runs["calls"].append({"cmd": cmd, "in_data": in_data, "sudoable": sudoable, "checkrc": checkrc})
        return runs["rc"], runs["stdout"], b""

    monkeypatch.setattr(bastion_ssh.SSHConnection, "_run", fake_run)
    return runs


def make_scp_connection(**options):
    defaults = {
        "ssh_transfer_method": "scp",
        "ssh_executable": "ssh",
        "sftp_executable": "sftp",
        "sftp_batch_mode": True,
        "sftp_extra_args": "",
    }
    conn = make_connection(**{**defaults, **options})
    conn.host = "target.example.com"
    conn._shell = FakeShell()
    return conn


def test_osh_command_goes_through_bastion_plugin(super_build):
    """Transfers run a bastion "--osh" plugin for the target host."""
    conn = make_scp_connection()

    conn._build_osh_command("scp", "--scp-cmd", bastion_ssh.encode_scp_cmd("scp -t /tmp/a#b c"))

    assert super_build == [
        {
            "subsystem": "ssh",
            "args": [
                "-T",
                "bastion.example.com",
                "--",
                "--user",
                "root",
                "--port",
                "2200",
                "--host",
                "target.example.com",
                "--osh",
                "scp",
                "--scp-cmd",
                "scp#-t#/tmp/a##b#c",
            ],
            "port": 2222,
            "user": "bastion_user",
        }
    ]
    assert conn.get_option("port") == 2200
    assert conn.get_option("remote_user") == "root"


def test_put_file_speaks_scp_protocol(tmp_path, scp_run):
    """put sends the scp file header, the data and an ack to "scp -t"."""
    src = tmp_path / "src"
    src.write_bytes(b"hello\0world")
    src.chmod(0o640)
    scp_run["stdout"] = b"\0\0\0"
    conn = make_scp_connection()

    result = conn._file_transport_command(str(src), "/tmp/dest file", "put")

    assert result == (0, b"\0\0\0", b"")
    call = scp_run["calls"][0]
    assert call["cmd"][-1] == "scp#-t#'/tmp/dest#file'"
    assert call["in_data"] == b"C0640 11 dest file\nhello\0world\0"
    assert call["sudoable"] is False
    assert call["checkrc"] is False


def test_put_file_raises_on_scp_error(tmp_path, scp_run):
    """An scp error sent by the remote is reported."""
    src = tmp_path / "src"
    src.write_bytes(b"data")
    scp_run["stdout"] = b"\0\1scp: /nope/dest: No such file or directory\n"
    conn = make_scp_connection()

    with pytest.raises(bastion_ssh.AnsibleError, match="No such file or directory"):
        conn._file_transport_command(str(src), "/nope/dest", "put")


def test_fetch_file_speaks_scp_protocol(tmp_path, scp_run):
    """fetch sends acks to "scp -f", and writes the received data."""
    dest = tmp_path / "dest"
    scp_run["stdout"] = b"C0644 11 src\nhello\0world\0"
    conn = make_scp_connection()

    result = conn._file_transport_command("/tmp/src", str(dest), "get")

    assert result == (0, b"", b"")
    assert dest.read_bytes() == b"hello\0world"
    call = scp_run["calls"][0]
    assert call["cmd"][-1] == "scp#-f#/tmp/src"
    assert call["in_data"] == b"\0\0\0"


@pytest.mark.parametrize(
    "stdout",
    [
        b"\1scp: /tmp/src: No such file or directory\n",
        b"C0644 11 src\nhello",
        b"",
    ],
)
def test_fetch_file_raises_on_scp_error(tmp_path, scp_run, stdout):
    """An scp error or a truncated transfer is reported, and no file is written."""
    dest = tmp_path / "dest"
    scp_run["stdout"] = stdout
    conn = make_scp_connection()

    with pytest.raises(bastion_ssh.AnsibleError, match="failed to fetch"):
        conn._file_transport_command("/tmp/src", str(dest), "get")

    assert not dest.exists()


def test_other_transfer_methods_use_parent(monkeypatch):
    """Only the scp and sftp transfer methods are handled by the plugin."""
    seen = []

    def fake_transport(self, in_path, out_path, sftp_action):
        seen.append((in_path, out_path, sftp_action))
        return 0, b"", b""

    monkeypatch.setattr(bastion_ssh.SSHConnection, "_file_transport_command", fake_transport)
    conn = make_scp_connection(ssh_transfer_method="piped")

    conn._file_transport_command("/a", "/b", "put")

    assert seen == [("/a", "/b", "put")]


def test_quote_sftp_direct_arg():
    """Arguments are quoted for OpenSSH argv_split(): only backslashes and quotes are escaped."""
    assert bastion_ssh.quote_sftp_direct_arg("a b#c") == b'"a b#c"'
    assert bastion_ssh.quote_sftp_direct_arg("x=\"y\" 'z' \\") == b'"x=\\"y\\" \\\'z\\\' \\\\"'


@pytest.mark.parametrize("sftp_action", ["put", "get"])
def test_sftp_transfer_goes_through_bastion_sftp_plugin(scp_run, sftp_action):
    """sftp runs the bastion "--osh sftp" plugin with -D, and sends the batch command on stdin."""
    conn = make_scp_connection(ssh_transfer_method="sftp")

    result = conn._file_transport_command("/tmp/src", "/tmp/dest file", sftp_action)

    assert result == (0, b"", b"")
    call = scp_run["calls"][0]
    assert call["cmd"] == [
        b"sftp",
        b"-b",
        b"-",
        b"-D",
        b'"ssh" "-T" "bastion.example.com" "--" "--user" "root" "--port" "2200" '
        b'"--host" "target.example.com" "--osh" "sftp"',
    ]
    assert call["in_data"] == sftp_action.encode() + b" /tmp/src '/tmp/dest file'\n"
    assert call["sudoable"] is False
    assert call["checkrc"] is False


def test_sftp_transfer_options(scp_run):
    """sftp_batch_mode and sftp_extra_args are honored."""
    conn = make_scp_connection(ssh_transfer_method="sftp", sftp_batch_mode=False, sftp_extra_args="-l 1000")

    conn._file_transport_command("/tmp/src", "/tmp/dest", "put")

    assert scp_run["calls"][0]["cmd"][:4] == [b"sftp", b"-l", b"1000", b"-D"]


def test_sftp_transfer_raises_on_error(scp_run):
    """A failed sftp transfer is reported."""
    scp_run["rc"] = 1
    scp_run["stdout"] = b"remote open(\"/nope/dest\"): No such file or directory\n"
    conn = make_scp_connection(ssh_transfer_method="sftp")

    with pytest.raises(bastion_ssh.AnsibleError, match="No such file or directory"):
        conn._file_transport_command("/tmp/src", "/nope/dest", "put")


# Tests for mitogen


@pytest.fixture
def mitogen_strategy(monkeypatch):
    """Install the connection loader patch of the mitogen strategies."""
    strategy = pytest.importorskip("ansible_mitogen.strategy")
    monkeypatch.setattr(
        bastion_ssh.connection_loader, "get_with_context", strategy.wrap_connection_loader__get_with_context
    )


def test_no_mitogen_connection_without_mitogen_strategy():
    """Without a mitogen strategy, the plugin stays an ssh connection."""
    assert bastion_ssh.get_mitogen_connection_class() is None


def test_init_switches_to_mitogen_connection(monkeypatch, mitogen_strategy):
    """With a mitogen strategy, the connection created by Ansible becomes a mitogen connection."""
    import ansible_mitogen.connection

    mitogen_class = bastion_ssh.get_mitogen_connection_class()
    init_args = []
    monkeypatch.setattr(mitogen_class, "__init__", lambda self, *args, **kwargs: init_args.append((args, kwargs)))
    conn = make_connection()

    bastion_ssh.Connection.__init__(conn, "play_context", new_stdin=None)

    assert type(conn) is mitogen_class
    assert isinstance(conn, ansible_mitogen.connection.Connection)
    assert conn.plugin_type == "connection"
    assert init_args == [(("play_context",), {"new_stdin": None})]


def test_mitogen_stack_goes_through_bastion(monkeypatch, mitogen_strategy):
    """The mitogen ssh hop connects to the bastion, which runs python on the target. Next hops are kept."""
    import ansible_mitogen.connection

    become_hop = {"method": "sudo", "kwargs": {"username": "www-data"}}
    stack = (
        {
            "method": "ssh",
            "kwargs": {
                "hostname": "target.example.com",
                "username": "root",
                "port": 2200,
                "python_path": ["/usr/bin/python3"],
                "ssh_args": ["-C"],
            },
        },
        become_hop,
    )
    monkeypatch.setattr(ansible_mitogen.connection.Connection, "_build_stack", lambda self: ("target", stack))
    conn = make_connection(bastion_ssh.get_mitogen_connection_class())

    inventory_name, new_stack = conn._build_stack()

    assert inventory_name == "target"
    assert new_stack == (
        {
            "method": "ssh",
            "kwargs": {
                "hostname": "bastion.example.com",
                "username": "bastion_user",
                "port": 2222,
                "python_path": [
                    "--",
                    "-q",
                    "-T",
                    "--never-escape",
                    "--user",
                    "root",
                    "--port",
                    "2200",
                    "target.example.com",
                    "--",
                    "/usr/bin/python3",
                ],
                "ssh_args": ["-C"],
            },
        },
        become_hop,
    )


def test_mitogen_stack_requires_bastion_settings(monkeypatch, mitogen_strategy):
    """Missing bastion settings are reported, as with the ssh connection."""
    import ansible_mitogen.connection

    stack = ({"method": "ssh", "kwargs": {"hostname": "target", "username": "root", "port": None}},)
    monkeypatch.setattr(ansible_mitogen.connection.Connection, "_build_stack", lambda self: ("target", stack))
    conn = make_connection(bastion_ssh.get_mitogen_connection_class(), bastion_host=None)

    with pytest.raises(bastion_ssh.AnsibleConnectionFailure, match="Missing bastion_host"):
        conn._build_stack()
