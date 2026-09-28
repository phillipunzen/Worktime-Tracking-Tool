#!/bin/sh
set -e

# Tabellen anlegen / Admin erzeugen (wartet automatisch auf die Datenbank)
flask init-db

exec gunicorn wsgi:app \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-3}" \
  --threads "${GUNICORN_THREADS:-2}" \
  --timeout 120 \
  --access-logfile -
