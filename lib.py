#! /usr/bin/env python

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


def get_hostvars(ipaddr):
    """Fetch hostvars for the given ipaddr

    As ansible-inventory use fqdn and not ipaddr we must fetch all inventory and
    browse it to select the correct variables

    :return: hostvars
    :rtype: dict
    """
    try:
        inventory = get_inventory()
        return [
            v
            for v in inventory.get("_meta", {}).get("hostvars", {}).values()
            if v.get("ansible_host") == ipaddr
        ][0]
    except IndexError:  # ipaddr not found in inventory, should never happen as this is called by ansible
        return {}

