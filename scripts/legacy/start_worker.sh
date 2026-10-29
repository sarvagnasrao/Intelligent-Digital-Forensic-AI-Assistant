#!/bin/bash
cd /root/idfa-worker
source ~/idfa-worker-venv/bin/activate
nohup python main.py > /tmp/worker.log 2>&1 &
echo $!