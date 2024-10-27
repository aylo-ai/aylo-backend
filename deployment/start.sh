#!/bin/bash

./manage.py collectstatic --no-input
./manage.py migrate --no-input
gunicorn -c deployment/gunicorn_conf.py config.wsgi