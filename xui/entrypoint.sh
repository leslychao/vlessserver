#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[xui-entrypoint] %s\n' "$*"
}

fail() {
  printf '[xui-entrypoint] ERROR: %s\n' "$*" >&2
  exit 1
}

normalize_base_path() {
  local value="${1:-/}"
  [[ "$value" == /* ]] || value="/$value"
  [[ "$value" == */ ]] || value="$value/"
  printf '%s' "$value"
}

require_env() {
  local name="$1"
  local value="${!name:-}"
  [[ -n "$value" ]] || fail "Required environment variable $name is not set"
}

require_env XUI_ADMIN_USERNAME
require_env XUI_ADMIN_PASSWORD

panel_port="${XUI_PANEL_PORT:-20530}"
panel_listen_ip="${XUI_PANEL_LISTEN_IP:-0.0.0.0}"
panel_base_path="$(normalize_base_path "${XUI_PANEL_WEB_BASE_PATH:-/admin/}")"
tls_enabled="${XUI_PANEL_TLS_ENABLED:-true}"

log "Applying panel account and network settings"
/app/x-ui setting \
  -username "$XUI_ADMIN_USERNAME" \
  -password "$XUI_ADMIN_PASSWORD" \
  -port "$panel_port" \
  -webBasePath "$panel_base_path" \
  -listenIP "$panel_listen_ip" \
  -resetTwoFactor true >/dev/null

if [[ "$tls_enabled" == "true" ]]; then
  cert_file="${XUI_PANEL_CERT_FILE:-}"
  key_file="${XUI_PANEL_KEY_FILE:-}"

  if [[ -z "$cert_file" || -z "$key_file" ]]; then
    cert_dir="/root/cert/self-signed"
    cert_file="$cert_dir/panel.crt"
    key_file="$cert_dir/panel.key"
    mkdir -p "$cert_dir"

    if [[ ! -s "$cert_file" || ! -s "$key_file" ]]; then
      log "Generating self-signed panel certificate"
      openssl req -x509 -nodes -newkey rsa:4096 -sha256 -days 3650 \
        -subj "/CN=${XUI_PANEL_CERT_COMMON_NAME:-proxy-stack-panel}" \
        -keyout "$key_file" \
        -out "$cert_file" >/dev/null 2>&1
      chmod 0600 "$key_file"
      chmod 0644 "$cert_file"
    fi
  fi

  [[ -s "$cert_file" ]] || fail "Panel certificate file does not exist: $cert_file"
  [[ -s "$key_file" ]] || fail "Panel key file does not exist: $key_file"

  log "Applying panel TLS certificate paths"
  /app/x-ui cert -webCert "$cert_file" -webCertKey "$key_file" >/dev/null
else
  log "Panel TLS disabled by environment"
  /app/x-ui cert -reset >/dev/null || true
fi

log "Starting 3x-ui"
exec /app/DockerEntrypoint.sh "$@"

