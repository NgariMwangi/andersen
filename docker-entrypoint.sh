#!/bin/sh
set -e

EMPLOYEE_UPLOAD_ROOT="${EMPLOYEE_UPLOADS_ROOT:-/employeeuploads}"
APP_UPLOAD_ROOT="${UPLOAD_FOLDER:-/app/uploads}"
LOG_ROOT="${LOG_DIR:-/app/logs}"

# Host bind mounts are often root-owned; the app runs as appuser (uid 1000).
mkdir -p "$EMPLOYEE_UPLOAD_ROOT" "$APP_UPLOAD_ROOT" "$LOG_ROOT" \
  "$APP_UPLOAD_ROOT/leave_requests" "$APP_UPLOAD_ROOT/employees"
chown -R appuser:appuser "$EMPLOYEE_UPLOAD_ROOT" 2>/dev/null || true
chown -R appuser:appuser "$APP_UPLOAD_ROOT" 2>/dev/null || true
chown -R appuser:appuser "$LOG_ROOT" 2>/dev/null || true

exec gosu appuser "$@"
