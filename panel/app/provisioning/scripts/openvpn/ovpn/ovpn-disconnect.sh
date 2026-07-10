#!/usr/bin/env bash
# OpenVPN client-disconnect hook.
# Appends one accounting event per finished session. The ovpn-manager `enforce`
# job consolidates these into state.usedBytes (authoritative, once per session,
# no double counting). Always exits 0 (never block on disconnect).
#
# OpenVPN sets: common_name, bytes_received, bytes_sent (session totals).
set -uo pipefail
EVENTS="/etc/openvpn/ovpn-manager/usage-events.log"
NAME="${common_name:-}"
RECV="${bytes_received:-0}"
SENT="${bytes_sent:-0}"
[ -n "$NAME" ] || exit 0
# normalise possibly-empty numbers
case "$RECV" in ''|*[!0-9]*) RECV=0;; esac
case "$SENT" in ''|*[!0-9]*) SENT=0;; esac
printf '%s %s %s %s\n' "$(date +%s)" "$NAME" "$RECV" "$SENT" >>"$EVENTS" 2>/dev/null || true
exit 0
