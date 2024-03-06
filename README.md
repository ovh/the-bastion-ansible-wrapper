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

Ensure the scripts are executable (`chmod +x`)

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

If not set, the cache will not be used, even if `cache` is set at the Ansible level.

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

The location of the configuration file can be set with `BASTION_CONFIG_FILE`
environment variable (defaults to `/etc/ovh/bastion/config.yml`).

## Configuration priority

Source of variables are read in the following order:
* Ansible playbook `environment`
* configuration file
* Ansible inventory
* operating system environment variables

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

This has been tested with

* Ansible 2.9.6
* Python 3.7.3
* SSH OpenSSH_7.9p1 Debian-10+deb10u2, OpenSSL 1.1.1d

## Debug

If this doesn't seem to work, run your ansible with `-vvvv`, you'll see whether it actually attempts to use the wrappers or not.

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
