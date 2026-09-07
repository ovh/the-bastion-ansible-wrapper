import os
import re
import shlex
import shutil
import sys
import time

# ssh(1) options taking a value, which the next argument holds when it is not
# attached to the option itself
SSH_OPTIONS_WITH_VALUE = "BbcDEeFIiJLlmOopQRSWw"

# ssh(1) options making it work locally and exit, without opening a connection
SSH_LOCAL_OPTIONS = "GOQV"

BASTION_VAR_NAMES = ("bastion_host", "bastion_port", "bastion_user")

# the ssh options carrying the bastion vars, keyed by their lowercase name
# as ssh(1) reads an option name whatever its case
BASTION_SSH_OPTIONS = {
    "bastionhost": "bastion_host",
    "bastionport": "bastion_port",
    "bastionuser": "bastion_user",
}

SHELL_SEPARATORS = ("&&", "||", ";", "|", "&")

# the flags a shell takes its command from, ex `/bin/sh -c '<command>'`
SHELL_COMMAND_FLAGS = ("-c", "-lc")

SHELL_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)

# the substring every bastion var name holds, whatever its case
BASTION_VAR_MARKER = "bastion"

# `/bin/sh -c '/bin/sh -c "..."'` is as deep as ansible nests its commands
MAX_COMMAND_DEPTH = 3

# a cache file written by another layout is read as no cache at all
CACHE_VERSION = 2


def find_executable(executable, path=None):
    """Find the absolute path of an executable

    :return: path
    :rtype: str
    """
    return shutil.which(executable, path=path)


def inventory_executable():
    """Find ansible-inventory, which every inventory lookup runs

    :return: path
    :rtype: str
    """
    inventory_cmd = find_executable("ansible-inventory")
    if not inventory_cmd:
        raise Exception("Failed to identify path of ansible-inventory")

    return inventory_cmd


def get_inventory(source=None):
    """Fetch ansible-inventory --list

    :return: inventory
    :rtype: dict
    """
    if source is None:
        source = get_inventory_source()

    # ex : export BASTION_ANSIBLE_INV_OPTIONS="-i my_inventory -i my_second_inventory"
    command = "{} {} --list".format(inventory_executable(), source["options"])

    return get_inv_from_command(command)


def get_inventory_source():
    """Identify what ansible-inventory is going to read

    A cache file holds the inventory of a single source, and a run reading
    another one has to list it rather than answer from that cache.

    :return: inventory source
    :rtype: dict
    """
    return {
        "options": os.environ.get("BASTION_ANSIBLE_INV_OPTIONS", ""),
        "inventory": os.environ.get("ANSIBLE_INVENTORY", ""),
        "config": os.environ.get("ANSIBLE_CONFIG", ""),
    }


def get_bastion_hostvars_from_cache(cache_file, cache_timeout, source):
    """Read the bastion vars of every host from the cache file

    :return: Inventory cache with `version` (the layout it was written in),
        `updated_at` (to expire the cache), `source` (the inventory it was
        written for), `hosts` (the bastion vars keyed by every name ansible may
        use) and `names` (the inventory name keyed the same way) keys.
    :rtype: dict
    """
    import json

    try:
        # Load JSON from cache file
        with open(cache_file, "r") as fd:
            cache = json.load(fd)
    except IOError:
        # File does not exist or path is incorrect
        return None
    except:
        # Invalid JSON or any other error
        pass
    else:
        # Check the layout, the cache expiry and the inventory it was written for
        if (
            cache.get("version") == CACHE_VERSION
            and cache.get("updated_at", 0) >= int(time.time()) - cache_timeout
            and cache.get("source") == source
        ):
            return cache

    # Cache expired, written by another version, or any other error
    try:
        os.remove(cache_file)
    except:
        pass

    return None


def write_bastion_hostvars_to_cache(cache_file, hosts, names, source):
    """Write the bastion vars of every host, with the layout, time and source"""
    import json

    cache = {
        "version": CACHE_VERSION,
        "hosts": hosts,
        "names": names,
        "updated_at": int(time.time()),
        "source": source,
    }
    with open(cache_file, "w") as fd:
        json.dump(cache, fd)


def map_bastion_hostvars(inventory):
    """Key the bastion vars of every host by every name ansible may reach it under

    Ansible either connects to the "ansible_host" inventory variable or to the
    hostname. Only the bastion vars are kept, their jinja vars resolved while
    the whole hostvars are still at hand, so that a lookup answers with what a
    cache can hold, rather than with the groups and the unrelated vars a
    listing carries and nothing here reads.

    :return: the bastion vars keyed by host, the inventory names keyed the same way
    :rtype: tuple
    """
    hosts = {}
    names = {}
    aliases = {}

    for name, hostvars in inventory.get("_meta", {}).get("hostvars", {}).items():
        hosts[name] = {
            var: get_var_within(hostvars[var], hostvars)
            for var in BASTION_VAR_NAMES
            if var in hostvars
        }
        names[name] = name
        ansible_host = hostvars.get("ansible_host")
        if ansible_host:
            aliases.setdefault(ansible_host, name)

    # an inventory name wins over the ansible_host another host answers to
    for ansible_host, name in aliases.items():
        hosts.setdefault(ansible_host, hosts[name])
        names.setdefault(ansible_host, name)

    return hosts, names


def read_bastion_hostvars(host, source, list_hosts):
    """Read the bastion vars of a host, filling the cache file on the way

    :return: the bastion vars of the host, the inventory name it is known under
    :rtype: tuple
    """
    cache_file = os.environ.get("BASTION_ANSIBLE_INV_CACHE_FILE")
    cache = None

    if cache_file:
        cache = get_bastion_hostvars_from_cache(
            cache_file=cache_file,
            cache_timeout=int(os.environ.get("BASTION_ANSIBLE_INV_CACHE_TIMEOUT", 60)),
            source=source,
        )

    if cache:
        hosts, names = cache["hosts"], cache["names"]
    else:
        hosts, names = list_hosts()
        if cache_file:
            write_bastion_hostvars_to_cache(cache_file, hosts, names, source)

    return hosts.get(host, {}), names.get(host)


def read_bastion_vars(hostvars):
    """Keep the bastion vars of a hostvars mapping, with their jinja vars resolved

    A var missing from the inventory is left out rather than held as None, so
    that the environment still answers for it.

    :return: bastion vars
    :rtype: dict
    """
    return {
        var: get_var_within(hostvars[var], hostvars)
        for var in BASTION_VAR_NAMES
        if var in hostvars
    }


def get_hostvars_of_one_host(host):
    """Ask ansible-inventory for a single host rather than for the whole inventory

    A listing renders the vars of every host and serializes every group with
    them, which each of the runs the wrapper makes pays for again. Asking for
    one host skips all of it, but it answers only where ansible connects to a
    host under its inventory name, so a miss falls back to the listing.

    :return: bastion vars
    :rtype: dict
    """
    command = "{} {} --host {}".format(
        inventory_executable(),
        get_inventory_source()["options"],
        shlex.quote(host),
    )

    try:
        # a host ansible reaches under another name is not an error here, it is
        # what the listing below is left to answer for
        hostvars = get_inv_from_command(command, quiet=True)
    except Exception:
        return {}

    return read_bastion_vars(hostvars)


def get_hostvars(host) -> dict:
    """Fetch the bastion vars for the given host

    :return: bastion vars
    :rtype: dict
    """
    if option_enabled("BASTION_ANSIBLE_INV_HOST_LOOKUP"):
        bastion_vars = get_hostvars_of_one_host(host)
        if bastion_vars:
            return bastion_vars

    source = get_inventory_source()
    bastion_vars, _ = read_bastion_hostvars(
        host, source, lambda: map_bastion_hostvars(get_inventory(source))
    )

    return bastion_vars


def parse_ssh_argv(argv):
    """Split ssh arguments into the options and what follows them

    An option value can look like anything, a hostname included, so the option
    arity is the only way to tell `ssh -o User=deploy 1.2.3.4` (a host, no
    command) from `ssh -W 1.2.3.4 bastion` (a bastion, no host).

    :return: the options, the option letters they hold, the host and command
    :rtype: tuple
    """
    options = []
    letters_given = set()
    remaining = list(argv)

    while remaining:
        token = remaining[0]
        if len(token) < 2 or not token.startswith("-"):
            break

        options.append(remaining.pop(0))
        if token == "--":
            break

        letters = token[1:]
        while letters:
            letter, letters = letters[0], letters[1:]
            letters_given.add(letter)
            if letter in SSH_OPTIONS_WITH_VALUE:
                # the value is the rest of the token, or the next argument
                if not letters and remaining:
                    options.append(remaining.pop(0))
                break

    return options, letters_given, remaining


def has_remote_command(argv):
    """Tell if the ssh arguments hold a host and a command to proxy

    Ansible also runs the ssh executable for operations that stay local, like
    closing a ControlPersist socket with `ssh -O stop <host>` or probing the
    version with `ssh -V`. Popping a host and a command out of those crashes
    the wrapper, and ansible reports the failure as an unreachable host with an
    empty message.

    :return: whether the connection can be proxied through the bastion
    :rtype: bool
    """
    _, letters_given, remaining = parse_ssh_argv(argv)

    if letters_given.intersection(SSH_LOCAL_OPTIONS):
        return False

    return len(remaining) >= 2


def split_command(command):
    """Split a command the way a shell would

    :return: tokens
    :rtype: list
    """
    try:
        return shlex.split(command)
    except ValueError:
        # an unbalanced quote, ex a command holding a lone apostrophe
        return command.split(" ")


def iter_shell_assignments(command, depth=0):
    """Yield the key and value of every assignment prefixing a command

    A shell reads `VAR=value` as an assignment only where a command can start,
    and ansible nests commands, ex:
        /bin/sh -c 'BASTION_HOST=host /usr/bin/python3 && sleep 0'
    so what a shell takes as a command is parsed as one rather than flattened
    with the command running it.

    :return: key, value
    :rtype: tuple
    """
    at_command_start = True
    previous = ""

    for token in split_command(command):
        # the fallback split keeps the quotes shlex would have consumed
        unquoted = token.lstrip("\"'")
        at_command_start = at_command_start or unquoted != token

        assignment = SHELL_ASSIGNMENT.match(unquoted)
        if at_command_start and assignment:
            yield assignment.group(1), assignment.group(2).strip("\"'")
            continue

        if previous in SHELL_COMMAND_FLAGS and depth < MAX_COMMAND_DEPTH:
            yield from iter_shell_assignments(token, depth + 1)

        at_command_start = unquoted in SHELL_SEPARATORS
        previous = unquoted


def parse_bastion_env_vars(command):
    """Fetch the bastion vars from the command ansible runs on the host

    The `environment` block of a playbook is inlined in the remote command, ex:
        /bin/sh -c 'BASTION_USER=user BASTION_HOST=host BASTION_PORT=22 /usr/bin/python3'

    Only an exact variable name matches, and only where a shell would read an
    assignment, so neither `NO_BASTION_HOST=1` nor the `bastion_host=x` a `raw`
    task happens to echo is read as a bastion var. An assignment without a
    value is skipped, letting the other sources of the bastion vars answer, and
    the first assignment wins, like in the environment the command ends up with.

    :return: bastion_host, bastion_port, bastion_user
    :rtype: tuple
    """
    # tokenizing costs more than the command length as it grows, and no
    # assignment can match without the substring every bastion var name holds
    if BASTION_VAR_MARKER not in command.lower():
        return None, None, None

    bastion_vars = dict.fromkeys(BASTION_VAR_NAMES)

    for key, value in iter_shell_assignments(command):
        name = key.lower()
        if name in bastion_vars and value and not bastion_vars[name]:
            bastion_vars[name] = value

    return (
        bastion_vars["bastion_host"],
        bastion_vars["bastion_port"],
        bastion_vars["bastion_user"],
    )


def read_bastion_option(option):
    """Read the bastion var an ssh option holds

    ssh(1) separates an option from its value with an equal sign or a space,
    and sftp and scp use the second form for the options they add themselves.

    :return: the bastion var name and its value, or None
    :rtype: tuple
    """
    name, separator, value = option.partition("=")
    if not separator:
        name, separator, value = option.partition(" ")
    if not separator:
        return None

    bastion_var = BASTION_SSH_OPTIONS.get(name.strip().lower())
    if not bastion_var:
        return None

    return bastion_var, value.strip()


def parse_bastion_ssh_options(argv):
    """Fetch the bastion vars from the ssh options and drop them from the arguments

    `ansible_ssh_common_args` is rendered from the hostvars of the moment, a
    `set_fact` included, and ansible appends it to the command line of all three
    wrappers, ex:
        ansible_ssh_common_args: -o BastionHost={{ bastion_host }}
    which is the only channel an sftp subsystem invocation carries, as it holds
    no command for an `environment` block to be inlined into.

    ssh knows no such option and would reject it, so it never reaches the
    bastion. An option without a value is dropped all the same, letting the
    other sources of the bastion vars answer, and the first one wins.

    :return: bastion_host, bastion_port, bastion_user, the remaining arguments
    :rtype: tuple
    """
    bastion_vars = dict.fromkeys(BASTION_VAR_NAMES)
    remaining = []
    reading_value = False

    for token in argv:
        option = None
        if reading_value:
            reading_value = False
            option = read_bastion_option(token)
            if not option:
                remaining.extend(["-o", token])
        elif token == "-o":
            reading_value = True
            continue
        elif token.startswith("-o") and len(token) > 2:
            option = read_bastion_option(token[2:])
            if not option:
                remaining.append(token)
        else:
            remaining.append(token)

        if option:
            name, value = option
            if value and not bastion_vars[name]:
                bastion_vars[name] = value

    if reading_value:
        remaining.append("-o")

    return (
        bastion_vars["bastion_host"],
        bastion_vars["bastion_port"],
        bastion_vars["bastion_user"],
        remaining,
    )


def manage_conf_file(conf_file, bastion_host, bastion_port, bastion_user):
    """Fetch the bastion vars from a config file.

    There will be set if not already defined, and before looking in the ansible inventory

    """

    if os.path.exists(conf_file):
        from yaml import YAMLError, safe_load

        try:
            with open(conf_file, "r") as f:
                yaml_conf = safe_load(f)

                if not bastion_host:
                    bastion_host = yaml_conf.get("bastion_host")
                if not bastion_port:
                    bastion_port = yaml_conf.get("bastion_port")
                if not bastion_user:
                    bastion_user = yaml_conf.get("bastion_user")

        except (YAMLError, IOError) as e:
            print("Error loading yaml file: {}".format(e))

    return bastion_host, bastion_port, bastion_user


def get_var_within(my_value, hostvar, check_list=None):
    """If a value is a jinja2 var, try to resolve it in the hostvars

    Ex:
        "my_value" == {{ my_jinja2_var }}
        "my_jinja2_var" == "foo"

    Will return "foo" for "my_value"

    """
    # keep track of parsed values
    # we want to avoid:
    # bastion_host == {{ foo }}
    # foo == {{ bastion_host }}
    if check_list is None:
        check_list = []

    if (
        isinstance(my_value, str)
        and my_value.startswith("{{")
        and my_value.endswith("}}")
    ):
        # ex: {{ my_jinja2_var }} -> lookup for 'my_jinja2_var' in hostvars
        key_name = my_value.replace("{{", "").replace("}}", "").strip()

        if key_name not in check_list:
            check_list.append(key_name)
            # resolve intricated vars
            return get_var_within(
                hostvar.get(key_name, ""), hostvar, check_list=check_list
            )
        else:
            return ""

    return my_value


def get_inv_from_command(command, quiet=False):
    import json
    import subprocess

    p = subprocess.Popen(
        command,
        shell=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output, error = p.communicate()
    if isinstance(output, bytes):
        output = output.decode()
    if not p.returncode:
        inventory = json.loads(output)
        return inventory
    else:
        if not quiet:
            if isinstance(error, bytes):
                error = error.decode(errors="replace")
            print(error, file=sys.stderr, end="")
        raise Exception("failed to get inventory")


def awx_get_inventory_file():
    # awx execution environment run dir, where the project and inventory are copied
    default_run_dir = "/runner"
    run_dir = os.environ.get("AWX_RUN_DIR", default_run_dir)
    return "{}/inventory/hosts".format(run_dir)


def awx_get_vars(host_ip, inventory_file):
    # the inventory file is a script that print the inventory in json format.
    # The ssh command sent only the IP to the ansible bastion wrapper, and
    # ansible either uses the "ansible_host" inventory variable or the
    # hostname, so the mapping answers to both. It goes through the same cache
    # file as a listing does, keyed on the inventory file it was built from.
    source = dict(get_inventory_source(), options="-i {}".format(inventory_file))
    bastion_vars, host = read_bastion_hostvars(
        host_ip,
        source,
        lambda: map_bastion_hostvars(get_inv_from_command(shlex.quote(inventory_file))),
    )

    # this should not happen
    if not host:
        return {}

    if all(bastion_vars.get(var) is not None for var in BASTION_VAR_NAMES):
        return bastion_vars

    # if some bastion vars are missing, maybe they are defined as group_vars.
    # We do an inventory lookup to get them.
    # With AWX no need to list the whole inventory, we already know the host
    command = "ansible-inventory -i {} --host {}".format(
        shlex.quote(inventory_file), shlex.quote(host)
    )
    return get_inv_from_command(command)


def source_enabled(name):
    """Tell whether a source of the bastion vars is enabled

    Every source is read unless its variable disables it, so that a setup
    knowing where its vars are skips the ones it has no use for.

    :return: source enabled
    :rtype: bool
    """
    return os.environ.get(name, "1").strip().lower() not in ("0", "no", "false", "off")


def option_enabled(name):
    """Tell whether an option is turned on, as none of them is by default

    :return: option enabled
    :rtype: bool
    """
    return os.environ.get(name, "0").strip().lower() in ("1", "yes", "true", "on")


def fill_bastion_vars(hostvar, bastion_host, bastion_port, bastion_user):
    """Fill the bastion vars an earlier source left unset

    Each one falls back to the inventory, then to the environment, then to a
    default, so that a var found earlier survives a lookup made for another one.
    """
    import getpass

    env = os.environ if source_enabled("BASTION_OS_ENV_ENABLED") else {}

    if not bastion_host:
        bastion_host = get_var_within(
            hostvar.get("bastion_host", env.get("BASTION_HOST")), hostvar
        )
    if not bastion_port:
        bastion_port = get_var_within(
            hostvar.get("bastion_port", env.get("BASTION_PORT", 22)), hostvar
        )
    if not bastion_user:
        bastion_user = get_var_within(
            hostvar.get("bastion_user", env.get("BASTION_USER", getpass.getuser())),
            hostvar,
        )

    return bastion_host, bastion_port, bastion_user


def check_bastion_host(bastion_host):
    """Abort when no bastion host was found"""
    if bastion_host:
        return

    sys.exit("bastion wrapper: no bastion host found for this connection")


def get_bastion_vars(host_vars):
    bastion_host = host_vars.get("bastion_host")
    bastion_user = host_vars.get("bastion_user")
    bastion_port = host_vars.get("bastion_port")
    return {
        "bastion_host": bastion_host,
        "bastion_port": bastion_port,
        "bastion_user": bastion_user,
    }
