#!/usr/bin/env bash
# Fetch a large release tarball onto a target whose network may reset long
# transfers.
#
# A plain `curl -fL --retry N` is not enough: curl only treats timeouts and a
# few HTTP status codes as "transient", so a mid-transfer RST (exit 56) is never
# retried, and without -C - a retry would restart from byte 0 anyway. This
# script escalates instead:
#
#   1. resume in place (-C -) for as long as each attempt makes progress
#   2. fall back to chunked HTTP Range fetches, which survive links that only
#      break on sustained transfers
#   3. verify the gzip stream before the caller extracts it, so a truncated
#      download fails here with a clear message instead of during tar
#
# Usage: fetch-bundle.sh <url> <dest>
set -uo pipefail

URL="${1:?usage: fetch-bundle.sh <url> <dest>}"
DEST="${2:?usage: fetch-bundle.sh <url> <dest>}"

CHUNK_BYTES="${CHUNK_BYTES:-2097152}"     # 2 MiB range requests
RESUME_ATTEMPTS="${RESUME_ATTEMPTS:-40}"  # cap on phase-1 resume rounds
STALL_LIMIT="${STALL_LIMIT:-4}"           # consecutive no-progress rounds before escalating
CHUNK_TRIES="${CHUNK_TRIES:-5}"           # per-chunk retries in phase 2
CHUNK_FAIL_LIMIT="${CHUNK_FAIL_LIMIT:-3}" # give up after this many unrecoverable chunks

size_of() { stat -c %s "$1" 2>/dev/null || echo 0; }

total_size() {
    curl -sIL --connect-timeout 20 --max-time 60 "$URL" \
        | awk 'BEGIN{IGNORECASE=1} /^content-length:/{v=$2} END{gsub(/\r/,"",v); print v}'
}

echo "Fetching $(basename "$DEST") ..."

# Check if destination file is already fully downloaded and valid
if [ -f "$DEST" ]; then
    if gzip -t "$DEST" 2>/dev/null; then
        echo "Bundle already downloaded and verified ($(size_of "$DEST") bytes)."
        exit 0
    else
        echo "Removing stale/incomplete bundle before download..."
        rm -f "$DEST" "${DEST}.part"
    fi
fi

TOTAL="$(total_size)"
if [ -n "$TOTAL" ]; then
    echo "  expected size: $TOTAL bytes"
else
    echo "  server did not report a size; will verify the archive instead"
fi

# -- phase 1: clean download first, then resume in place -----------------------
curl -fL --connect-timeout 20 --max-time 600 \
     --retry 3 --retry-all-errors --retry-delay 2 \
     -o "$DEST" -s "$URL"
rc=$?

if [ "$rc" = "0" ] && gzip -t "$DEST" 2>/dev/null; then
    echo "  downloaded and verified in 1 attempt ($(size_of "$DEST") bytes)"
    exit 0
fi

# If initial clean download didn't finish completely, resume with -C -
prev="$(size_of "$DEST")"
stall=0
for i in $(seq 1 "$RESUME_ATTEMPTS"); do
    curl -fL -C - --connect-timeout 20 --max-time 600 \
         --retry 3 --retry-all-errors --retry-delay 2 \
         -o "$DEST" -s "$URL"
    rc=$?
    now="$(size_of "$DEST")"

    if [ "$rc" = "0" ] && gzip -t "$DEST" 2>/dev/null; then
        echo "  downloaded and verified in $i attempt(s) ($now bytes)"
        exit 0
    fi
    if [ "$rc" = "33" ]; then
        echo "  server refuses resume; restarting from scratch"
        rm -f "$DEST"
        prev=0
        continue
    fi

    if [ "$now" -gt "$prev" ]; then
        stall=0
        echo "  attempt $i: $now bytes so far (rc=$rc)"
    else
        stall=$((stall + 1))
    fi
    prev="$now"

    if [ "$stall" -ge "$STALL_LIMIT" ]; then
        echo "  resume stalled at $now bytes; switching to chunked range fetch"
        break
    fi
done

# -- phase 2: chunked range fetch --------------------------------------------
if [ -n "$TOTAL" ] && [ "$(size_of "$DEST")" -lt "$TOTAL" ]; then
    off="$(size_of "$DEST")"
    fails=0
    tmp="${DEST}.part"
    while [ "$off" -lt "$TOTAL" ]; do
        end=$((off + CHUNK_BYTES - 1))
        [ "$end" -ge "$TOTAL" ] && end=$((TOTAL - 1))
        want=$((end - off + 1))

        ok=0
        for _ in $(seq 1 "$CHUNK_TRIES"); do
            rm -f "$tmp"
            if curl -fL -r "${off}-${end}" --connect-timeout 15 --max-time 120 -s -o "$tmp" "$URL"; then
                if [ "$(size_of "$tmp")" = "$want" ]; then ok=1; break; fi
            fi
            sleep 2
        done

        if [ "$ok" != "1" ]; then
            fails=$((fails + 1))
            echo "  chunk at offset $off failed"
            if [ "$fails" -ge "$CHUNK_FAIL_LIMIT" ]; then
                rm -f "$tmp"
                echo "ERROR: too many failed chunks; target network cannot sustain this download." >&2
                exit 75
            fi
            continue
        fi

        cat "$tmp" >> "$DEST"
        off=$((end + 1))
        [ $(( (off / CHUNK_BYTES) % 10 )) = 0 ] && echo "  $off / $TOTAL bytes"
    done
    rm -f "$tmp"
fi

# -- verify ------------------------------------------------------------------
got="$(size_of "$DEST")"
if gzip -t "$DEST" 2>/dev/null; then
    echo "Bundle downloaded and verified ($got bytes)."
    exit 0
fi

if [ -n "$TOTAL" ] && [ "$got" -lt "$TOTAL" ]; then
    echo "ERROR: incomplete download ($got of $TOTAL bytes)." >&2
    exit 75
fi

echo "ERROR: downloaded archive is corrupt (gzip check failed)." >&2
rm -f "$DEST" "${DEST}.part"
exit 75
