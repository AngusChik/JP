#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

cd jp
python manage.py collectstatic --no-input
