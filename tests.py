from lib import manage_conf_file
from yaml import dump

BASTION_HOST = "my_bastion"
BASTION_PORT = 22
BASTION_USER = "my_bastion_user"
BASTION_CONF_FILE = "/tmp/test_bastion_conf_file.yml"


def test_bastion_host_undefined():
    bastion_host, bastion_port, bastion_user = manage_conf_file(BASTION_CONF_FILE, None, BASTION_PORT, BASTION_USER)
    assert bastion_host == BASTION_HOST


def test_bastion_port_undefined():
    bastion_host, bastion_port, bastion_user = manage_conf_file(BASTION_CONF_FILE, BASTION_HOST, None, BASTION_USER)
    assert bastion_port == BASTION_PORT


def test_bastion_user_undefined():
    bastion_host, bastion_port, bastion_user = manage_conf_file(BASTION_CONF_FILE, BASTION_HOST, BASTION_PORT, None)
    assert bastion_user == BASTION_USER


def test_bastion_all_undefined():
    write_conf_file(BASTION_CONF_FILE)
    bastion_host, bastion_port, bastion_user = manage_conf_file(BASTION_CONF_FILE, None, None, None)
    assert bastion_user == BASTION_USER
    assert bastion_port == BASTION_PORT
    assert bastion_host == BASTION_HOST


def write_conf_file(conf_file):
    with open(conf_file, 'w') as f:

        data = {
            "bastion_host": BASTION_HOST,
            "bastion_port": BASTION_PORT,
            "bastion_user": BASTION_USER
        }

        dump(data, f)


write_conf_file(BASTION_CONF_FILE)
