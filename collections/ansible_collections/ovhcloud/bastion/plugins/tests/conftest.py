import sys
from pathlib import Path


def pytest_sessionstart(session):
    """
    Add the plugins/ directory to sys.path so tests can import:
      from connection.ssh import Connection
    """
    plugins_dir = Path(__file__).resolve().parent.parent
    if str(plugins_dir) not in sys.path:
        sys.path.insert(0, str(plugins_dir))
