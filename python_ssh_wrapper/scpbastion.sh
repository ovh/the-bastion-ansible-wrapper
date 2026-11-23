#!/bin/sh
exec scp -S $(dirname $0)/scpwrapper.py "$@"
