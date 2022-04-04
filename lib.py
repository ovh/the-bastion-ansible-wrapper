import json
import logging
import os
import subprocess


def find_executable(executable, path=None):
    """Find the absolute path of an executable

    :return: path
    :rtype: str
    """
    _, ext = os.path.splitext(executable)

    if os.path.isfile(executable):
        return executable

    if path is None:
        path = os.environ.get("PATH", os.defpath)

    for p in path.split(os.pathsep):
        f = os.path.join(p, executable)
        if os.path.isfile(f):
            return f


def get_inventory():
    """Fetch ansible-inventory --list

    :return: inventory
    :rtype: dict
    """
    inventory_cmd = find_executable("ansible-inventory")
    if not inventory_cmd:
        raise Exception("Failed to identify path of ansible-inventory")

    # ex : export BASTION_ANSIBLE_INV_OPTIONS="-i my_inventory -i my_second_inventory"
    inventory_options = os.environ.get("BASTION_ANSIBLE_INV_OPTIONS", "")

    command = "{} {} --list".format(inventory_cmd, inventory_options)
    p = subprocess.Popen(
        command,
        shell=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output, error = p.communicate()
    if type(output) is bytes:
        output = output.decode()
    if not p.returncode:
        return json.loads(output)
    else:
        logging.error(error)
        raise Exception("failed to query ansible-inventory")


def get_hostvars(host):
    """Fetch hostvars for the given host

    Ansible either uses the "ansible_host" inventory variable or the hostname.
    Fetch inventory and browse all hostvars to return only the ones for the host.

    :return: hostvars
    :rtype: dict
    """
    inventory = get_inventory()
    all_hostvars = inventory.get("_meta", {}).get("hostvars", {})
    for inventory_host, hostvars in all_hostvars.items():
        if inventory_host == host or hostvars.get("ansible_host") == host:
            return hostvars
    # Host not found
    return {}
