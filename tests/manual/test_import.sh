#!/bin/bash
cd /root/idfa-worker
source ~/idfa-worker-venv/bin/activate
python -c "import main; print('import ok')"