#!/bin/sh
exec sftp -S $(dirname $0)/sftpwrapper.py "$@"
