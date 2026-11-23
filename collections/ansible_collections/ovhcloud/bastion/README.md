This is the bastion ssh connection plugin, if you want to use [the bastion](https://ovh.github.io/the-bastion/) to connect to a host via Ansible.

The role of this plugin, is to make the standard ssh connection compatible with the bastion.

Take the following playbook:
```commandline
- hosts: 172.17.0.2
  remote_user: "root"
  tasks:
    - ansible.builtin.raw: ls /tmp
```

The command sent to the ssh plugin is basically :
```commandline
ssh -o 'User="root"' 172.17.0.2 'ls /tmp'
```

The role of the bastion ssh connection plugin is to transform this command to:
```commandline
ssh my_bastion_user@my_bastion.example.com -- root@172.17.0.2 -- 'ls /tmp'
```

It inherits from the builtin `ansible.builtin.ssh` connection plugin: all its options (`ssh_args`, `pipelining`, `ssh_executable`, ...) are still available.

# Installation

Copy this collection in an path reachable by the user used to execute Ansible playbooks.
ex:

cp -r collections /usr/share/ansible/

# Configuration

## define collection path

Make sure the collection path from the installation step is known from Ansible.

ex:
Ansible.cfg
```
[defaults]
collections_paths = ~/.ansible/collections:/usr/share/ansible/collections
```

## enable ssh plugin

The plugin can be made available:

- for all playbooks by default

in ansible configuration
```commandline
[defaults]
transport = ovhcloud.bastion.ssh
```

- individually in each playbook
```commandline
- hosts: "all"
  connection: ovhcloud.bastion.ssh
  tasks:
  ...
```

In all case, you also need to provide the following parameters:

- the bastion host
- the bastion port
- the bastion user

## Ansible config

You can setup the bastion in ansible configuration.
It will be used by default for all hosts.

```
[ovh]
bastion_host = my_bastion_host
bastion_user = my_bastion_user
bastion_port = 22
```

## Host / group vars

The bastion configuration can be provided as Ansible host / groups vars.
It will override the configurations defined in ansible.cfg

yaml inventory example:
```commandline
---
my_hosts:
  vars:
    bastion_host: "my_bastion_host"
    bastion_user: "my_bastion_user"
  hosts:
    my_host:
      bastion_port: 2222
```

## Environment variables

The bastion configuration can be provided as environment variables.
It will override the configurations defined in ansible.cfg and the host / group vars.

cli example:
```commandline
BASTION_USER="my_bastion_user" ansible-playbook -l my_host my_playbook.yml
```
Those are read on the controller: the `environment` playbook keyword (which sets variables on the remote host) has no effect on this plugin.

## ssh options

You can update the bastion ssh options too.
The default is:

`-q -T --never-escape`

It can defined in:

- ansible.cfg
```
[ovh]
# bastion ssh options can be redefined below
# this are the default in the plugin
# bastion_ssh_options = "-q -T --never-escape"
```

- host / group vars
yaml inventory example:
```
```commandline
---
my_hosts:
  vars:
    bastion_ssh_options: "-q -T --never-escape"
```

- environment variables
cli example:
```commandline
BASTION_SSH_OPTIONS="-q -T --never-escape" ansible-playbook -l my_host my_playbook.yml
```

## configuration sum up

| option              | host / group vars     | environment variable  | ansible.cfg `[ovh]`   | default                |
|---------------------|-----------------------|-----------------------|-----------------------|------------------------|
| bastion_host        | `bastion_host`        | `BASTION_HOST`        | `bastion_host`        | **required**           |
| bastion_user        | `bastion_user`        | `BASTION_USER`        | `bastion_user`        | **required**           |
| bastion_port        | `bastion_port`        | `BASTION_PORT`        | `bastion_port`        | `22`                   |
| bastion_ssh_options | `bastion_ssh_options` | `BASTION_SSH_OPTIONS` | `bastion_ssh_options` | `-q -T --never-escape` |

You can set up some generic configuration in ansible.cfg, and override them for specific use cases with vars.

Ex:
ansible.cfg
```
[ovh]
bastion_user = my_bastion_user
bastion_port = 22
```

Inventory
```commandline
---
webserver:
  vars:
    bastion_host: "my_bastion_host"

database:
  vars:
    bastion_host: "my_other_bastion_host"
```

# File transfers

Ansible provides different means to transfer files to the remote host through the bastion.
It may require some access rights on the bastion.

## scp

Configuration

ansible.cfg
```
[ssh_connection]
transfer_method = scp
```
This will copy the module to execute on the remote host using scp.
It requires the *scpdownload* right on the bastion.

You can also download files, like with [the fetch module](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/fetch_module.html)
This requires the *scpdownload* right on the bastion

## sftp

Configuration

ansible.cfg
```
[ssh_connection]
transfer_method = sftp
```
This will copy the module to execute on the remote host, and fetch files, using sftp
It requires the *sftp* right on the bastion.

## piped

Configuration

ansible.cfg
```
[ssh_connection]
transfer_method = piped
```
This will pipe *dd* through ssh to copy the module to execute on the remote host
This does not require any special right on the bastion

# Mitogen

This module is natively compatible with the [mitogen lib](https://mitogen.networkgenomics.com/ansible_detailed.html)
There is no specific configuration outside the mitogen one.

Configuration example:
ansible.cfg
```
[defaults]
transport = ovhcloud.bastion.ssh

# mitogen generic configuration
action_plugins = ./plugins/action:project/plugins/action:/usr/share/ansible/plugins/action:/home/my_user/venv3/lib/python3.12/site-packages/ansible_mitogen/plugins/action
strategy_plugins = /home/my_user/work/venv3/lib/python3.12/site-packages/ansible_mitogen/plugins/strategy
strategy = mitogen_linear
```

# Tests

```commandline
cd plugins/tests && pytest
```
