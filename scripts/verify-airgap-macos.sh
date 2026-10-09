#!/usr/bin/env bash
# Prove the engine needs no network: run a full index + search inside a macOS
# sandbox that denies every non-loopback connection. Requires models to be pulled.
# (Linux equivalent:  unshare -rn sextant index <folder>   or   docker run --network none ...)
set -euo pipefail
FOLDER="${1:?usage: verify-airgap-macos.sh <folder-of-documents>}"
SEXTANT="${SEXTANT:-sextant}"
MODELS="${SEXTANT_HOME:-$HOME/.sextant}/models"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
ln -s "$MODELS" "$WORK/models"
PROFILE='(version 1)(allow default)(deny network-outbound)(allow network-outbound (remote ip "localhost:*"))(allow network-outbound (remote unix-socket))'
echo "1. Control: the sandbox really blocks the internet"
if sandbox-exec -p "$PROFILE" curl -s -m 5 -o /dev/null https://huggingface.co; then
  echo "   sandbox is NOT blocking network; aborting"; exit 1
else echo "   blocked, as expected"; fi
echo "2. Index inside the sandbox"
SEXTANT_HOME="$WORK" sandbox-exec -p "$PROFILE" "$SEXTANT" index "$FOLDER" 2>/dev/null | tail -n 2
echo "3. Search inside the sandbox"
SEXTANT_HOME="$WORK" sandbox-exec -p "$PROFILE" "$SEXTANT" search "${2:-risk}" -k 1 2>/dev/null | head -n 4
echo "PASS: indexed and searched with all outbound network denied."
