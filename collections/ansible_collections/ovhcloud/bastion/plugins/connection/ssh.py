"""SSH connection plugin going through an OVHcloud bastion (https://ovh.github.io/the-bastion/)."""

import functools
import os
import shlex
import sys

import yaml

from ansible.errors import AnsibleConnectionFailure, AnsibleError
from ansible.module_utils.common.text.converters import to_bytes, to_text
from ansible.plugins.connection.ssh import DOCUMENTATION as SSH_DOCUMENTATION
from ansible.plugins.connection.ssh import Connection as SSHConnection
from ansible.plugins.loader import connection_loader


def _bastion_option(name, description, value_type="str", default=None):
    return {
        "description": description,
        "type": value_type,
        "default": default,
        # Ansible precedence: ini < vars (inventory host / group vars, play vars, extra vars)
        # Environment variables are not declared here, as Ansible would give them a lower precedence than vars:
        # they are handled in Connection._get_bastion_option to override everything.
        "ini": [{"section": "ovh", "key": name}],
        "vars": [{"name": name}],
    }


def _build_documentation():
    # The ssh connection plugin documentation is not available as a doc fragment, so we extend it at import time.
    # Ansible registers the plugin options from the module DOCUMENTATION attribute, which makes the "vars" sources
    # declared below available to the plugin: the TaskExecutor templates them from the host vars and passes them
    # to set_options() before each task.
    doc = yaml.safe_load(SSH_DOCUMENTATION)
    doc["short_description"] = "connect via ssh through an OVHcloud bastion"
    doc["options"].update(
        {
            "bastion_host": _bastion_option("bastion_host", "Bastion host."),
            "bastion_port": _bastion_option("bastion_port", "Bastion port.", "int", 22),
            "bastion_user": _bastion_option("bastion_user", "Bastion account."),
            "bastion_ssh_options": _bastion_option(
                "bastion_ssh_options",
                "Options given to the bastion for the connection to the target host.",
                default="-q -T --never-escape",
            ),
        }
    )
    return yaml.safe_dump(doc)


DOCUMENTATION = _build_documentation()

# scp protocol acknowledgement
SCP_ACK = b"\0"


def encode_scp_cmd(scp_cmd):
    # encoding expected by the bastion "--scp-cmd" option: "#" is doubled, then spaces are replaced by "#"
    return scp_cmd.replace("#", "##").replace(" ", "#")


def scp_error(output):
    # scp errors are sent as "\x01message\n" (warning) or "\x02message\n" (fatal)
    return to_text(output.strip(b"\0\1\2\n"), errors="surrogate_or_replace")


def quote_sftp_direct_arg(arg):
    # "sftp -D" splits its command with OpenSSH argv_split(): inside double quotes, only \\, \" and \' are escapes
    arg = to_bytes(arg, errors="surrogate_or_strict")
    for char in (b"\\", b"'", b'"'):
        arg = arg.replace(char, b"\\" + char)
    return b'"' + arg + b'"'


class BastionSettings:
    """Bastion settings, shared by the ssh and mitogen connections."""

    def _get_bastion_option(self, name):
        # precedence: ansible.cfg < host / group vars < environment variables (on the controller)
        env_value = os.environ.get(name.upper())
        if env_value is not None:
            return env_value
        return self.get_option(name)

    def _get_bastion_settings(self, target_host):
        bastion_host = self._get_bastion_option("bastion_host")
        bastion_user = self._get_bastion_option("bastion_user")
        target_user = self.get_option("remote_user")

        missing = [
            name
            for name, value in (
                ("bastion_host", bastion_host),
                ("bastion_user", bastion_user),
                ("remote_user", target_user),
            )
            if not value
        ]
        if missing:
            raise AnsibleConnectionFailure(
                f"Missing {', '.join(missing)} to connect to {target_host} through the bastion. "
                "Set them in host / group vars, environment variables or the [ovh] section of ansible.cfg."
            )
        return bastion_host, bastion_user, target_user

    def _bastion_args(self, target_user, target_port, target_host):
        # arguments of the bastion ssh command, before the remote command.
        # The first "--" stops the ssh client option parsing.
        return [
            "--",
            *shlex.split(self._get_bastion_option("bastion_ssh_options")),
            "--user",
            target_user,
            "--port",
            str(target_port or 22),
            target_host,
            "--",
        ]


def get_mitogen_connection_class():
    # Mitogen strategies patch connection_loader.get_with_context to replace the connection plugins they know
    # (ssh, local...) by their own. This plugin is not one of them: it checks the patch to switch to mitogen itself.
    mitogen_strategy = sys.modules.get("ansible_mitogen.strategy")
    if (
        mitogen_strategy is None
        or connection_loader.get_with_context is not mitogen_strategy.wrap_connection_loader__get_with_context
    ):
        return None
    return _build_mitogen_connection_class()


@functools.cache
def _build_mitogen_connection_class():
    # imported only with a mitogen strategy, mitogen is not required otherwise
    from ansible_mitogen.plugins.connection.mitogen_ssh import Connection as MitogenSSHConnection

    # The class must be named "Connection": Ansible computes the plugin type (for its options) from the class name.
    class Connection(BastionSettings, MitogenSSHConnection):
        """
        Mitogen starts its python interpreter on the target with
            ssh <ssh options> target_user@target_host:target_port python_path -c <bootstrap>
        The bastion arguments are added in front of python_path, to run
            ssh <ssh options> bastion_user@bastion_host:bastion_port -- <bastion_ssh_options> --user target_user
                --port target_port target_host -- python_path -c <bootstrap>
        Commands and file transfers then go through this mitogen channel (transfer_method is not used).
        """

        def _build_stack(self):
            inventory_name, stack = super()._build_stack()
            # The first hop is the ssh connection from the controller,
            # the next ones (become) are run by mitogen on the target.
            hop = stack[0]
            if hop["method"] != "ssh":
                return inventory_name, stack

            kwargs = dict(hop["kwargs"])
            target_host = kwargs["hostname"]
            bastion_host, bastion_user, _ = self._get_bastion_settings(target_host)
            bastion_args = self._bastion_args(kwargs["username"], kwargs["port"], target_host)
            kwargs.update(
                hostname=bastion_host,
                username=bastion_user,
                port=self._get_bastion_option("bastion_port"),
                python_path=[*bastion_args, *kwargs["python_path"]],
            )
            return inventory_name, (dict(hop, kwargs=kwargs), *stack[1:])

    return Connection


class Connection(BastionSettings, SSHConnection):
    """
    Transform
        ssh target_user@target_host:target_port cmd
    into
        ssh bastion_user@bastion_host:bastion_port -- <bastion_ssh_options> --user target_user --port target_port target_host -- cmd

    With transfer_method = scp, file transfers run
        ssh bastion_user@bastion_host:bastion_port -- --user target_user --port target_port --host target_host --osh scp --scp-cmd "scp -t|-f path"
    and the plugin speaks the scp protocol on its stdin / stdout.

    With transfer_method = sftp, file transfers run
        sftp -b - -D "ssh bastion_user@bastion_host:bastion_port -- --user target_user --port target_port --host target_host --osh sftp"
    the sftp client speaks the sftp protocol directly with the bastion sftp plugin.

    With a mitogen strategy, the connection becomes the mitogen connection built by _build_mitogen_connection_class.
    """

    # Only the commands built by exec_command are sent through the bastion.
    # Other _build_command callers ("ssh -O stop" on reset, transfers of the "smart" method) are left untouched.
    _through_bastion = False

    def __init__(self, *args, **kwargs):
        mitogen_connection = get_mitogen_connection_class()
        if mitogen_connection is not None:
            # Ansible creates the instance from this class: switch it to the mitogen class
            self.__class__ = mitogen_connection
            mitogen_connection.__init__(self, *args, **kwargs)
            return
        super().__init__(*args, **kwargs)

    def exec_command(self, cmd, in_data=None, sudoable=True):
        self._through_bastion = True
        try:
            return super().exec_command(cmd, in_data=in_data, sudoable=sudoable)
        finally:
            self._through_bastion = False

    def _build_command(self, binary, subsystem, *other_args):
        if not self._through_bastion or subsystem != "ssh":
            return super()._build_command(binary, subsystem, *other_args)

        # SSHConnection.exec_command calls us with ([-tt], target_host, cmd)
        *ssh_args, target_host, remote_cmd = other_args
        bastion_host, bastion_user, target_user = self._get_bastion_settings(target_host)

        # remote_cmd is kept as a single argument to preserve its spaces and newlines.
        bastion_args = [*self._bastion_args(target_user, self.get_option("port"), target_host), remote_cmd]
        return self._build_bastion_command(binary, subsystem, bastion_user, *ssh_args, bastion_host, *bastion_args)

    def _file_transport_command(self, in_path, out_path, sftp_action):
        # put_file / fetch_file entry point, self.host is already set
        method = self.get_option("ssh_transfer_method")
        if method == "sftp":
            return self._sftp_transfer(in_path, out_path, sftp_action)
        if method != "scp":
            return super()._file_transport_command(in_path, out_path, sftp_action)
        if sftp_action == "put":
            return self._scp_put(in_path, out_path)
        return self._scp_fetch(in_path, out_path)

    def _sftp_transfer(self, in_path, out_path, sftp_action):
        cmd = [to_bytes(self.get_option("sftp_executable"), errors="surrogate_or_strict")]
        if self.get_option("sftp_batch_mode"):
            # a failed transfer makes sftp exit with an error
            cmd += [b"-b", b"-"]
        extra_args = self.get_option("sftp_extra_args")
        if extra_args:
            cmd += [to_bytes(arg, errors="surrogate_or_strict") for arg in self._split_ssh_args(extra_args)]
        # -D: sftp runs this command instead of "ssh -s target_host sftp", and speaks sftp on its stdin / stdout
        cmd += [b"-D", b" ".join(quote_sftp_direct_arg(arg) for arg in self._build_osh_command("sftp"))]

        in_data = to_bytes(f"{sftp_action} {shlex.quote(in_path)} {shlex.quote(out_path)}\n", errors="surrogate_or_strict")
        # SSHConnection._run retries on connection failures
        returncode, stdout, stderr = self._run(cmd, in_data, sudoable=False, checkrc=False)

        if returncode != 0:
            raise AnsibleError(
                f"failed to transfer file through the bastion with sftp ({sftp_action} {in_path} {out_path} "
                f"on {self.host}):\n{to_text(stdout)}\n{to_text(stderr)}"
            )
        return returncode, stdout, stderr

    def _scp_put(self, in_path, out_path):
        b_in_path = to_bytes(in_path, errors="surrogate_or_strict")
        with open(b_in_path, "rb") as f:
            data = f.read()
        # like scp: the file is created with the local mode, minus the remote umask
        mode = os.stat(b_in_path).st_mode & 0o777
        name = to_bytes(os.path.basename(out_path), errors="surrogate_or_strict")

        # the remote "scp -t" sends an ack when it starts, after the file header, and after the file data
        in_data = b"C%04o %d %s\n" % (mode, len(data), name) + data + SCP_ACK
        returncode, stdout, stderr = self._run_scp(f"scp -t {self._shell.quote(out_path)}", in_data)

        if stdout != SCP_ACK * 3:
            raise AnsibleError(
                f"failed to transfer file {in_path} to {self.host}:{out_path} through the bastion: "
                f"{scp_error(stdout)}\n{to_text(stderr)}"
            )
        return returncode, stdout, stderr

    def _scp_fetch(self, in_path, out_path):
        # the remote "scp -f" waits for an ack before the file header, before the file data, and at the end
        returncode, stdout, stderr = self._run_scp(f"scp -f {self._shell.quote(in_path)}", SCP_ACK * 3)

        # expected output: b"C<mode> <size> <name>\n" + data + ack
        header, _, payload = stdout.partition(b"\n")
        try:
            if not header.startswith(b"C"):
                raise ValueError
            size = int(header.split(b" ", 2)[1])
        except (IndexError, ValueError):
            size = None
        if size is None or payload[size:] != SCP_ACK:
            raise AnsibleError(
                f"failed to fetch file {self.host}:{in_path} to {out_path} through the bastion: "
                f"{scp_error(stdout if size is None else payload[size:])}\n{to_text(stderr)}"
            )

        with open(to_bytes(out_path, errors="surrogate_or_strict"), "wb") as f:
            f.write(payload[:size])
        return returncode, b"", stderr

    def _run_scp(self, scp_cmd, in_data):
        cmd = self._build_osh_command("scp", "--scp-cmd", encode_scp_cmd(scp_cmd))
        # SSHConnection._run retries on connection failures
        return self._run(cmd, in_data, sudoable=False, checkrc=False)

    def _build_osh_command(self, osh_plugin, *plugin_args):
        # ssh command running the bastion plugin osh_plugin (scp / sftp) for the target host
        bastion_host, bastion_user, target_user = self._get_bastion_settings(self.host)
        bastion_args = [
            "--",
            "--user",
            target_user,
            "--port",
            str(self.get_option("port") or 22),
            "--host",
            self.host,
            "--osh",
            osh_plugin,
            *plugin_args,
        ]
        return self._build_bastion_command(
            self.get_option("ssh_executable"), "ssh", bastion_user, "-T", bastion_host, *bastion_args
        )

    def _build_bastion_command(self, binary, subsystem, bastion_user, *other_args):
        # SSHConnection._build_command reads the user and port from the plugin options:
        # point them to the bastion only while the command is built.
        target_user = self.get_option("remote_user")
        target_port = self.get_option("port")
        self.set_option("port", self._get_bastion_option("bastion_port"))
        self.set_option("remote_user", bastion_user)
        try:
            return super()._build_command(binary, subsystem, *other_args)
        finally:
            self.set_option("port", target_port)
            self.set_option("remote_user", target_user)
