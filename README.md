This repository offers 2 ways of using [The OVH bastion](https://github.com/ovh/the-bastion) with Ansible.

# The goal

Basically, when using the bastion with Ansible, we want to change the original ssh command to one compatible with the bastion.
Ex, targeting a host with *172.17.0.2* ip, through *my_bastion.example.com*

We want to go from this (minus the ssh options for readibility):
```
ssh -o 'User="root"' 172.17.0.2 'ls /tmp'
```

to this:
```
ssh my_bastion_user@my_bastion.example.com -- root@172.17.0.2 -- 'ls /tmp'
```

# The means

Boths means are compatible with the bastion SSH / SCP / SFTP.
They are also compatible with the [mitogen lib](https://mitogen.networkgenomics.com/ansible_detailed.html)

They work both with ansible and AWX.

They differ in their Ansible integration and their ways of resolving bastions configurations.

Please read respective README for detailled configuratons.

## python ssh wrapper

This is the former way of using Ansible with the bastion.
It will replace (wrap) your ssh binary.

You can provide your bastion's hostname (or ip) / user / port via:
- env vars
- a dedicated configuration file
- ansible host / group vars

If using host / group vars, the wrapper will do an inventory lookup in order to find the host from its IP, and get its vars.
It will do so for each host / each task, unless you configure some cache.

Connection debug example:
```
<172.17.0.2> SSH: EXEC /usr/share/ansible/plugins/bastion/sshwrapper.py -vvv -o 'User="root"' -tt 172.17.0.2 '/bin/sh -c '"'"'/usr/bin/python3 && sleep 0'"'"''
```

We only have the informations known by ansible:
- the ansible host ip
- the anbile host ssh port
- the ansible host ssh user

The bastion related data are managed by the wrapper and unknown to the ansible command.

## Ansible ssh plugin

This is a most recent way to use the Bastion with Ansible, provided as a collection, in compliance with Ansible standards.
The collection provides an Ansible SSH plugin in the ovhcloud namespace.

You can provide your bastion's hostname (or ip) / user / port via:
- env vars
- ansible host / group vars
- ansible.cfg

Being integrated in Ansible, it has direct access to the Ansible vars to find the bastion configuration.
And it can provide all informations in the ssh command.

Connection debug example:
```
<172.17.0.2> SSH: EXEC ssh -vvv -o Port=22  'User="my_bastion_user"' my_bastion.example.com -- -q -T --never-escape --user root --port 22 172.17.0.2 -- '/bin/sh -c '"'"'/usr/bin/python3 && sleep 0'"'"''
```

All informations are present in the connection debug:
- the bastion user
- the bastion port
- the bastion hostname
- the ansible host ip
- the anbile host ssh port
- the ansible host ssh user


