#!/usr/bin/env bash
# udp2raw_setup.sh – create or edit udp2raw systemd services
#   chmod +x udp2raw_setup.sh && sudo ./udp2raw_setup.sh
set -euo pipefail

BIN_DIR="/usr/local/bin/udp2raw"
BIN_FILE="${BIN_DIR}/udp2raw"

green(){ printf '\e[32m%s\e[0m\n' "$1"; }
red()  { printf '\e[31m%s\e[0m\n' "$1"; }

###############################################################################
# 0. Install udp2raw if missing
###############################################################################
install_udp2raw() {
  green "→ Installing udp2raw ..."
  apt update
  apt install -y git build-essential golang
  TMP=$(mktemp -d)
  git clone https://github.com/MikeWang000000/udp2raw.git "$TMP/udp2raw"
  make -C "$TMP/udp2raw"
  mkdir -p "$BIN_DIR"
  cp -r "$TMP/udp2raw"/* "$BIN_DIR/"
  rm -rf "$TMP"
  green "✔ udp2raw installed to $BIN_DIR"
}
[[ -x "$BIN_FILE" ]] || install_udp2raw

###############################################################################
# 1. Helpers
###############################################################################
sanitize_alias() {
  local raw="$1"
  local mod="${raw#tcp-}"        # remove leading tcp-
  mod="${mod#udp2raw-}"          # remove leading udp2raw-
  mod="${mod%-udp2raw}"          # remove trailing -udp2raw
  echo "$mod"
}

list_services() {
  mapfile -t SVCS < <(ls /etc/systemd/system/tcp-*-udp2raw.service 2>/dev/null || true)
  ((${#SVCS[@]})) || { red "No udp2raw services found."; exit 1; }
  echo "Existing udp2raw services:"
  for i in "${!SVCS[@]}"; do printf "%2s) %s\n" $((i+1)) "$(basename "${SVCS[$i]}")"; done
}

update_execstart() { sed -i "s|^ExecStart=.*|ExecStart=$2|" "$1"; }

###############################################################################
# 2. Modify existing service
###############################################################################
modify_service() {
  list_services
  read -rp "Select service to modify: " IDX
  [[ $IDX =~ ^[0-9]+$ ]] || { red "Invalid number"; exit 1; }
  SERVICE_FILE="${SVCS[$((IDX-1))]}"
  SERVICE_NAME=$(basename "$SERVICE_FILE")
  cur=$(grep -Po '^ExecStart=.*' "$SERVICE_FILE" | cut -d= -f2-)
  echo -e "\nCurrent ExecStart:\n${cur}\n"

  read -rp "New tunnel mode (faketcp/udp/icmp): " NEW_MODE
  NEW_MODE=${NEW_MODE,,}

  if [[ "$NEW_MODE" == "icmp" ]]; then
    new=$(echo "$cur" \
            | sed -E 's/--raw-mode[ ]+[a-z]+/--raw-mode icmp/' \
            | sed -E 's/[ ]*--fake-http[ ]+[^ ]+//' \
            | sed -E 's/[ ]*--seq-mode[ ]+[0-9]+//')
  else
    read -rp "Fake domain (e.g. brave.example.com): " NEW_D
    [[ "$cur" =~ ' -c ' ]] && [[ $NEW_D != tcp-* ]] && NEW_D="tcp-${NEW_D}"
    new=$(echo "$cur" \
            | sed -E "s/--raw-mode[ ]+[a-z]+/--raw-mode ${NEW_MODE}/")
    if echo "$new" | grep -q -- '--fake-http'; then
      new=$(echo "$new" | sed -E "s/--fake-http[ ]+[^ ]+/--fake-http ${NEW_D}/")
    else
      new="$new --fake-http ${NEW_D}"
    fi
    # ensure --seq-mode 2 present only for faketcp
    if [[ "$NEW_MODE" == "faketcp" ]]; then
      echo "$new" | grep -q -- '--seq-mode' || new="$new --seq-mode 2"
    else
      new=$(echo "$new" | sed -E 's/[ ]*--seq-mode[ ]+[0-9]+//')
    fi
  fi

  update_execstart "$SERVICE_FILE" "$new"
  systemctl daemon-reload
  systemctl restart "$SERVICE_NAME"
  green "✔ ${SERVICE_NAME} updated and restarted."
  systemctl status "$SERVICE_NAME" --no-pager
  exit 0
}

###############################################################################
# 3. Create / overwrite service
###############################################################################
create_service() {
  echo "------------------------------------------------------------"
  echo "  udp2raw Service Generator"
  echo "------------------------------------------------------------"
  echo "1) Foreign server  (mode: -s)"
  echo "2) Iran server     (mode: -c)"
  read -rp "Select configuration (1/2): " MODE

  read -rp "Service alias (e.g. brave): " RAW_ALIAS
  SERVICE_ALIAS=$(sanitize_alias "$RAW_ALIAS")
  [[ -n "$SERVICE_ALIAS" ]] || { red "Alias cannot be empty."; exit 1; }
  SERVICE_NAME=$(echo "tcp-${SERVICE_ALIAS}-udp2raw" | tr -s '-')
  SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

  if [[ "$MODE" == "1" ]]; then
    read -rp "Listening port on foreign server (PORT_LISTEN): " PORT_LISTEN
    read -rp "Local WireGuard port (PORT_WG): " PORT_WG
    read -rp "Tunnel mode (faketcp/udp/icmp): " TUNNEL_MODE
    if [[ "$TUNNEL_MODE" == "icmp" ]]; then
      FAKE_ARG=""
    else
      read -rp "Fake domain (e.g. brave.example.com): " FAKE_DOMAIN
      FAKE_ARG="--fake-http ${FAKE_DOMAIN}"
    fi
    EXEC_CMD="${BIN_FILE} -s -l0.0.0.0:${PORT_LISTEN} -r127.0.0.1:${PORT_WG} \
-k \"Aa@!123456\" --raw-mode ${TUNNEL_MODE} ${FAKE_ARG} \
--cipher-mode aes128cbc --auth-mode hmac_sha1"
    [[ "$TUNNEL_MODE" == "faketcp" ]] && EXEC_CMD+=" --seq-mode 2"
  elif [[ "$MODE" == "2" ]]; then
    read -rp "Local port in Iran (IRAN_PORT): " IRAN_PORT
    read -rp "Foreign server IP (FOREIGN_IP): " FOREIGN_IP
    read -rp "udp2raw port on foreign server (FOREIGN_PORT): " FOREIGN_PORT
    read -rp "Tunnel mode (faketcp/udp/icmp): " TUNNEL_MODE
    if [[ "$TUNNEL_MODE" == "icmp" ]]; then
      FAKE_ARG=""
    else
      read -rp "Fake domain (e.g. brave.example.com): " FAKE_DOMAIN
      [[ $FAKE_DOMAIN == tcp-* ]] || FAKE_DOMAIN="tcp-${FAKE_DOMAIN}"
      FAKE_ARG="--fake-http ${FAKE_DOMAIN}"
    fi
    EXEC_CMD="${BIN_FILE} -c -l0.0.0.0:${FOREIGN_PORT} -r\"${FOREIGN_IP}\":${IRAN_PORT} \
-k \"Aa@!123456\" --raw-mode ${TUNNEL_MODE} ${FAKE_ARG} \
--cipher-mode aes128cbc --auth-mode hmac_sha1"
    [[ "$TUNNEL_MODE" == "faketcp" ]] && EXEC_CMD+=" --seq-mode 2"
  else
    red "Invalid selection"; exit 1
  fi

  cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=udp2raw tunnel (${SERVICE_ALIAS})
After=network.target

[Service]
Type=simple
User=root
ExecStart=${EXEC_CMD}
Restart=no

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now "${SERVICE_NAME}.service"
  green "✔ Service ${SERVICE_NAME}.service created and started."
  systemctl status "${SERVICE_NAME}.service" --no-pager
}

###############################################################################
# 4. Main menu
###############################################################################
echo "1) Create / overwrite a service"
echo "2) Modify existing service (change tunnel mode)"
read -rp "Choose action (1/2): " ACTION
[[ "$ACTION" == "2" ]] && modify_service || create_service
