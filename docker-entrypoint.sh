#!/bin/sh
set -e

UPLOAD_ROOT="${EMPLOYEE_UPLOADS_ROOT:-/employeeuploads}"

# Host bind mounts are often root-owned; the app runs as appuser (uid 1000).
mkdir -p "$UPLOAD_ROOT"
chown -R appuser:appuser "$UPLOAD_ROOT" 2>/dev/null || true

exec gosu appuser "$@"
