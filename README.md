# Using Ansible SSH Connection through The Bastion

The three scripts in this directory are a wrapper around Ansible native SSH
connection, so that [The Bastion](https://github.com/ovh/the-bastion/) can be transparently used along with Ansible.
You have to set some os SSH Ansible variables as defined in
https://docs.ansible.com/ansible/latest/plugins/connection/ssh.html in addition
with `BASTION_USER`, `BASTION_PORT` and `BASTION_HOST`. It can also rely on
`ansible-inventory` to identify `bastion_user`, `bastion_host`, `bastion_port`.
`ansible-inventory` takes precedences over environment variables as this will
allow to use different bastion for different hosts.

## Simple usage with environment variables

Ensure the scripts are executable (`chmod +x`) and install their
dependencies (`pip install -r requirements.txt`)

```bash
export BASTION_USER="bastion_user"
export BASTION_HOST="bastion.example.org"
export BASTION_PORT=22
export ANSIBLE_PIPELINING=1
export ANSIBLE_SCP_IF_SSH="True"
export ANSIBLE_PRIVATE_KEY_FILE="${HOME}/.ssh/id_rsa"
export ANSIBLE_SSH_EXECUTABLE="CHANGE_THIS_PATH_TO_THE_PROPER_ONE/sshwrapper.py"
export ANSIBLE_SCP_EXECUTABLE="CHANGE_THIS_PATH_TO_THE_PROPER_ONE/scpbastion.sh"

ansible all -i hosts -m raw -a uptime

ansible all -i hosts -m ping
```

## Leveraging Ansible inventory

`ansible-inventory` provides access to host's variables. This plugin takes
advantage of this to look for `bastion_*`.

In the following example all hosts will use the same `your-bastion-user`. The hosts
in `zone_secure` will reach the bastion `your-supersecure-bastion` on port 222
the others hosts will use  `your-bastion` on port 22.

```yaml
$ grep -ri bastion group_vars/
group_vars/all.yml:bastion_user: <your-bastion-user>
group_vars/all.yml:bastion_host: <your-bastion>
group_vars/all.yml:bastion_port: 22
group_vars/zone_secure.yml:bastion_port: 222
group_vars/zone_secure.yml:bastion_host: <your-supersecure-bastion>
```

For more information have a look at [the official documentation](https://docs.ansible.com/ansible/latest/network/getting_started/first_inventory.html).

## Ansible inventory cache

Because `ansible-inventory` command can be slow, the Ansible inventory results can be saved to a file to speed up
multiple calls with the following environment variables:
* `BASTION_ANSIBLE_INV_CACHE_FILE`: path to the cache file on the filesystem
* `BASTION_ANSIBLE_INV_CACHE_TIMEOUT`: number of seconds before refreshing the cache

Note: the cache file will not be removed by the wrapper at the end of the run, which means that multiple consecutive runs might use it, as long as it's fresh enough (the expiration of `BASTION_ANSIBLE_INV_CACHE_TIMEOUT` will force a refresh).

A cache file holds the inventory of a single source. A run reading another one, through `BASTION_ANSIBLE_INV_OPTIONS`, `ANSIBLE_INVENTORY` or `ANSIBLE_CONFIG`, lists it again and replaces the cache rather than answering from the inventory of the previous run.

The wrapper runs once per task and per host, and lists the inventory on each of those runs when it needs it. Setting the cache file is what turns that into a single listing for the whole playbook.

If not set, the cache will not be used, even if `cache` is set at the Ansible level.

A cache file holds the bastion vars alone, keyed by every name Ansible may reach a host under, with their Jinja references already resolved. The groups and the unrelated host variables a listing carries are dropped, as nothing in the wrapper reads them: on an inventory of 3000 groups and 2000 hosts that is 0.6 MB read in 2.7 ms rather than 4.9 MB read in 21 ms, on every run the wrapper makes.

A cache file written by an older version of the wrapper is read as no cache at all, and replaced by a listing.

## Asking for a single host

`ansible-inventory --list` renders the variables of every host and serializes every group with them, and the wrapper runs once per task and per host. Setting `BASTION_ANSIBLE_INV_HOST_LOOKUP` to `1` asks `ansible-inventory --host <host>` for the one host being connected to instead, which skips all of it.

The lookup answers only where Ansible connects to a host under its inventory name. A host reached through its `ansible_host` variable is not found by name, and the wrapper falls back to the listing, so the option costs one extra `ansible-inventory` run per connection on an inventory that sets `ansible_host` everywhere. It is off by default for that reason: turn it on when your inventory names are what Ansible connects to.

## Using env vars from a playbook

In some cases, like the usage of multiple bastions for a single ansible controller and multiple inventory sources, it may be useful to set the vars in the environment configuration from the playbook.

It can also be combined with the group_vars.

Example:
```yaml
---
- hosts: all
  gather_facts: false
  environment:
    BASTION_USER: "{{ bastion_user }}"
    BASTION_HOST: "{{ bastion_host }}"
    BASTION_PORT: "{{ bastion_port }}"
  tasks:
  ...
```

here, each host may have its bastion_X vars defined in group_vars and host_vars.

If environement vars are not defined, or if the module does not send them, then the sshwrapper is doing a lookup on the ansible-inventory to fetch the bastion_X vars.

## Using vars known at runtime

A playbook `environment` block reaches the ssh wrapper only, and only for the
command a module runs: ansible inlines it in that command, and it has nowhere to
go when there is no command. An SFTP transfer asks for a subsystem, an SCP
transfer runs a command the local `scp` binary writes, and ansible creates the
temporary directory a module is copied into with a command of its own. None of
those carry the block, so a variable known only at runtime cannot be read from
there.

`ansible_ssh_common_args` is rendered from the host variables of the moment and
appended to the command line of all three wrappers, which makes it the one
channel reaching every hop:

```yaml
---
- hosts: all
  gather_facts: false
  tasks:
    - name: read the bastion of this host from wherever it lives
      set_fact:
        bastion_host: "{{ netbox_device.custom_fields.bastion }}"

    - name: hand the bastion vars over to the wrappers
      set_fact:
        ansible_ssh_common_args: >-
          -o BastionUser={{ bastion_user }}
          -o BastionHost={{ bastion_host }}
          -o BastionPort={{ bastion_port }}
```

It is a host variable like any other, so an inventory, a `group_vars` file or a
`vars_files` entry can define it just as well.

The wrappers read these three options and drop them from the command line they
hand over, as ssh knows no option by those names. Every other option is
forwarded untouched.

## Using vars from a config file

For some use cases (AWX in a non containerised environment for instance), the environment is overridden by the job, and there is no fixed inventory source path.

So we may not get the vars from the environment nor the inventory.

In this case, we may use a configuration file to provide the BASTION vars.

Example:

```
cat /etc/ovh/bastion/config.yml

---
bastion_host: "my_great_bastion"
bastion_port: 22
bastion_user: "my_bastion_user"
```

The configuration file is read after checking the environment variables sent in the ssh command line, and will only set them if not defined.

The location of the configuration file can be set with `BASTION_CONF_FILE`
environment variable (defaults to `/etc/ovh/bastion/config.yml`).

## Configuration priority

Source of variables are read in the following order:
* `BastionUser`, `BastionHost` and `BastionPort` ssh options
* Ansible playbook `environment`
* configuration file
* Ansible inventory
* operating system environment variables

A source is read only when a variable is still missing, and the first one
holding it wins.

## Disabling a source

Each source is enabled by default and can be turned off with its own
environment variable, set to `0`, `no`, `false` or `off`:

| Variable | Source |
| --- | --- |
| `BASTION_SSH_OPTIONS_ENABLED` | `Bastion*` ssh options |
| `BASTION_PLAYBOOK_ENV_ENABLED` | Ansible playbook `environment` |
| `BASTION_CONF_FILE_ENABLED` | configuration file |
| `BASTION_ANSIBLE_INVENTORY_ENABLED` | Ansible inventory |
| `BASTION_OS_ENV_ENABLED` | operating system environment variables |

The wrapper runs once per task and per host, so a source it does not need still
costs a file read or an `ansible-inventory` run on each of those. A setup
knowing where its variables are can skip the others:

```bash
export BASTION_HOST="bastion.example.org"
export BASTION_ANSIBLE_INVENTORY_ENABLED=0
export BASTION_CONF_FILE_ENABLED=0
```

The `Bastion*` ssh options are dropped from the command line whatever
`BASTION_SSH_OPTIONS_ENABLED` is set to, as ssh would reject them.

`BASTION_OS_ENV_ENABLED` covers the `BASTION_USER`, `BASTION_HOST` and
`BASTION_PORT` variables only. The variables of this table are read whatever it
is set to, and so are `BASTION_CONF_FILE` and the `BASTION_ANSIBLE_INV_*` ones.

## Using multiple inventories sources

The wrapper is going to lookup the ansible inventory to look for the host and its vars.

You may define multiple inventories sources in an ENV var. Example:

```
export BASTION_ANSIBLE_INV_OPTIONS='-i my_first_inventory_source -i my_second_inventory_source'
```

## Using the bastion wrapper with AWX

When using AWX, the inventory is available as a file in the AWX Execution Environment.
It is then easy and much faster to get the appropriate host from the IP sent by Ansible to the bastion wrapper.

When AWX usage is detected, the bastion wrapper is going to:
- lookup in the inventory file for the appropriate host
- lookup for the bastion vars in the host_vars
- if not found, run an inventory lookup on the host to get the group_vars too (and execute eventual vars plugins)

The AWX usage is detected by looking for the inventory file, the default path being "/runner/inventory/hosts"
The path may be changed y setting an "AWX_RUN_DIR" environment variable on the AWX worker.
Ex on a AWX k8s instance group:
```
      env:
      - name: "AWX_RUN_DIR"
        value: "/my_folder/my_sub_folder"
```
The inventory file will be looked up at "/my_folder/my_sub_folder/inventory/hosts"

## Connection via SSH

The wrapper can be configured using `ansible.cfg` file as follow:

```ini
[ssh_connection]
pipelining = True
ssh_executable = ./extra/bastion/sshwrapper.py
```

Or by using the `ANSIBLE_SSH_PIPELINING` and `ANSIBLE_SSH_EXECUTABLE`
environment variables.

## Connection via Mitogen

[Mitogen](https://mitogen.networkgenomics.com/ansible_detailed.html) replaces
Ansible's connection plugin with one of its own. It reads the same
`ssh_executable`, so the wrapper needs no configuration beyond the one above:

```ini
[defaults]
strategy_plugins = <path to ansible_mitogen>/plugins/strategy
strategy = mitogen_linear

[ssh_connection]
ssh_executable = ./extra/bastion/sshwrapper.py
```

Mitogen builds its own `ssh` command line rather than reusing Ansible's, which
differs in two ways the wrapper accounts for. It names the remote user and port
with the short `-l` and `-p` flags rather than with `-o User=` and `-o Port=`,
and it hands the remote command over as several arguments rather than as one,
each already quoted for the shell that will run it. The wrapper joins them with
a space and quotes none of them, which is what `ssh` itself does.

## File transfer using SFTP

By default, Ansible uses SFTP to copy files. The executable should be defined
as follow in the ansible.cfg file:

```ini
[ssh_connection]
transfer_method = sftp
sftp_executable = ./extra/bastion/sftpbastion.sh
```

Or by using the `ANSIBLE_SFTP_EXECUTABLE` environment variable.

## File transfer using SCP (deprecated)

The SCP protocol is still allowed but will soon deprecated by OpenSSH. You
should consider using SFTP instead. If you still want to use the SCP protocol,
you can define the method and executable as follow:

File ansible.cfg:

```ini
[ssh_connection]
transfer_method = scp
scp_if_ssh = True       # Ansible < 2.17
scp_extra_args = -O     # OpenSSH >= 9.0
scp_executable = ./extra/bastion/scpbastion.sh
```

Or by using the following environment variables:
* `ANSIBLE_SCP_IF_SSH`
* `ANSIBLE_SSH_TRANSFER_METHOD`
* `ANSIBLE_SCP_EXTRA_ARGS`
* `ANSIBLE_SCP_EXECUTABLE`

## Configuration example

File ansible.cfg:

```ini
[ssh_connection]
pipelining = True
ssh_executable = ./extra/bastion/sshwrapper.py
sftp_executable = ./extra/bastion/sftpbastion.sh
```

## Integration via submodule

You can include this repository as a submodule in your playbook repository

```bash
git submodule add https://github.com/ovh/the-bastion-ansible-wrapper.git extra/bastion
```

## Requirements

The wrappers need the python dependencies listed in `requirements.txt`:

```bash
pip install -r requirements.txt
```

This has been tested with

* Debian 12 and Debian 13, the supported Debian releases
* Python 3.11 and 3.13, the versions those releases ship
* ansible-core 2.19
* OpenSSH 9.2

## Debug

If this doesn't seem to work, run your ansible with `-vvvv`, you'll see whether it actually attempts to use the wrappers or not.

### no bastion host found for this connection

The wrapper found `bastion_host` in none of the sources listed in
[Configuration priority](#configuration-priority). Define it as `bastion_host`
in the Ansible inventory, as `BASTION_HOST` in the environment, or as
`bastion_host` in the configuration file, and check that the source you use is
not turned off, see [Disabling a source](#disabling-a-source).

The most common cause is an inventory passed on the command line with
`ansible -i my_inventory.yml`: the wrapper is executed by Ansible in place of
ssh, it does not receive the command line of the ansible run, and its own
`ansible-inventory --list` therefore reads the default inventory instead of
yours. Either declare the inventory in `ansible.cfg`:

```ini
[defaults]
inventory = my_inventory.yml
```

or point the wrapper at it:

```bash
export BASTION_ANSIBLE_INV_OPTIONS='-i my_inventory.yml'
```

## Lint

Just use [pre-commit](https://pre-commit.com/).

TLDR:
* pip install --user pre-commit
* pre-commit install
* git commit

# Related

- [The Bastion](https://github.com/ovh/the-bastion) - Authentication, authorization, traceability and auditability for SSH accesses.

# License

Copyright OVH SAS

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
