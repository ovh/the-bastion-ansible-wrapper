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

For more information have a look at [the official documentation](https://docs.ansible.com/ansible/latest/network/getting_started/first_inventory.html)

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

## Using multiple inventories sources

The wrapper is going to lookup the ansible inventory to look for the host and its vars.

You may define multiple inventories sources in an ENV var. Example: 

export BASTION_ANSIBLE_INV_OPTIONS='-i my_first_inventory_source -i my_second_inventory_source'

## Configuration via ansible.cfg

```ini
[ssh_connection]
scp_if_ssh = True
# Rely on bastion wrapper
pipelining = True
ssh_executable = ./extra/bastion/sshwrapper.py
scp_executable = ./extra/bastion/scpbastion.sh
transfer_method =  scp
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

