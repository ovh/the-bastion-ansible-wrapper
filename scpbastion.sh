#!/bin/sh
exec scp -O -S $(dirname $0)/scpwrapper.py "$@"
