import os

from yaml import dump

from lib import (
    awx_get_inventory_file,
    get_bastion_vars,
    get_var_within,
    manage_conf_file,
)

BASTION_HOST = "my_bastion"
BASTION_PORT = 22
BASTION_USER = "my_bastion_user"
BASTION_CONF_FILE = "/tmp/test_bastion_conf_file.yml"


def test_manage_conf_file_bastion_host_undefined():
    bastion_host, bastion_port, bastion_user = manage_conf_file(
        BASTION_CONF_FILE, None, BASTION_PORT, BASTION_USER
    )
    assert bastion_host == BASTION_HOST


def test_manage_conf_file_bastion_port_undefined():
    bastion_host, bastion_port, bastion_user = manage_conf_file(
        BASTION_CONF_FILE, BASTION_HOST, None, BASTION_USER
    )
    assert bastion_port == BASTION_PORT


def test_manage_conf_file_bastion_user_undefined():
    bastion_host, bastion_port, bastion_user = manage_conf_file(
        BASTION_CONF_FILE, BASTION_HOST, BASTION_PORT, None
    )
    assert bastion_user == BASTION_USER


def test_manage_conf_file_bastion_all_undefined():
    write_conf_file(BASTION_CONF_FILE)
    bastion_host, bastion_port, bastion_user = manage_conf_file(
        BASTION_CONF_FILE, None, None, None
    )
    assert bastion_user == BASTION_USER
    assert bastion_port == BASTION_PORT
    assert bastion_host == BASTION_HOST


def write_conf_file(conf_file):
    with open(conf_file, "w") as f:

        data = {
            "bastion_host": BASTION_HOST,
            "bastion_port": BASTION_PORT,
            "bastion_user": BASTION_USER,
        }

        dump(data, f)


write_conf_file(BASTION_CONF_FILE)


def test_get_var_within_one_level():
    hostvars = {"bastion_host": "{{ bastion_fqdn }}", "bastion_fqdn": "my_real_bastion"}
    bastion_host = get_var_within(hostvars["bastion_host"], hostvars)
    assert bastion_host == hostvars["bastion_fqdn"]


def test_get_var_within_two_levels():
    hostvars = {
        "bastion_host": "{{ bastion_fqdn }}",
        "bastion_fqdn": "{{ my_other_var }}",
        "my_other_var": "my_real_bastion",
    }
    bastion_host = get_var_within(hostvars["bastion_host"], hostvars)
    assert bastion_host == hostvars["my_other_var"]


def test_get_var_within_not_found():
    hostvars = {"bastion_host": "{{ bastion_fqdn }}"}
    bastion_host = get_var_within(hostvars["bastion_host"], hostvars)
    assert not bastion_host


def test_get_var_within_infinite():
    hostvars = {
        "bastion_host": "{{ bastion_fqdn }}",
        "bastion_fqdn": "{{ bastion_host }}",
    }
    bastion_host = get_var_within(hostvars["bastion_host"], hostvars)
    assert not bastion_host


def test_get_var_not_a_jinja2_var():
    hostvars = {"bastion_host": "{{ bastion_fqdn"}
    bastion_host = get_var_within(hostvars["bastion_host"], hostvars)
    assert bastion_host == hostvars["bastion_host"]


def test_get_var_not_a_string():
    hostvars = {"bastion_host": 68}
    bastion_host = get_var_within(hostvars["bastion_host"], hostvars)
    assert bastion_host == hostvars["bastion_host"]


def test_awx_get_inventory_file_default():
    assert awx_get_inventory_file() == "/runner/inventory/hosts"


def test_awx_get_inventory_file_env_defined():
    env_path = "/my_awx"
    os.environ["AWX_RUN_DIR"] = env_path
    assert awx_get_inventory_file() == f"{env_path}/inventory/hosts"
    os.environ.pop("AWX_RUN_DIR")


def test_get_bastion_vars():
    host_vars = {
        "bastion_port": BASTION_PORT,
        "bastion_host": BASTION_HOST,
        "bastion_user": BASTION_USER,
    }
    bastion_vars = get_bastion_vars(host_vars)
    assert (
        bastion_vars["bastion_port"] == BASTION_PORT
        and bastion_vars["bastion_host"] == BASTION_HOST
        and bastion_vars["bastion_user"] == BASTION_USER
    )


def test_get_bastion_vars_not_full():
    host_vars = {"bastion_port": BASTION_PORT, "bastion_user": BASTION_USER}
    bastion_vars = get_bastion_vars(host_vars)
    assert not bastion_vars["bastion_host"]
