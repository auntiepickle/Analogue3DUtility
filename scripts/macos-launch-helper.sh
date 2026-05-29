#!/bin/bash
#
# macOS launch helper for the Analogue 3D Utility binary (a3d-macos).
#
# RECOVERY TOOL: this is mainly useful if you already downloaded the binary in a
# browser (which quarantines it). The easier path is to download with `curl`,
# which doesn't quarantine the file at all - then you don't need this. See MACOS.md.
#
# It clears the quarantine flag and makes the binary executable. It does NOT
# bypass Gatekeeper - you may still need to approve it once in
# System Settings > Privacy & Security on first run.
#
# Usage:
#   chmod +x macos-launch-helper.sh
#   ./macos-launch-helper.sh [path-to-a3d-macos]   # defaults to ./a3d-macos

set -e

BINARY="${1:-a3d-macos}"

if [ ! -f "$BINARY" ]; then
    echo "Error: '$BINARY' not found."
    echo "Usage: $0 [path-to-a3d-macos]"
    echo "Put this script next to the binary, or pass its path."
    exit 1
fi

echo "=== Analogue 3D Utility - macOS launch helper ==="
echo "Preparing: $BINARY"
echo

echo "-> Clearing quarantine / extended attributes..."
if xattr -cr "$BINARY" 2>/dev/null; then
    echo "   done."
elif sudo xattr -cr "$BINARY" 2>/dev/null; then
    echo "   done (needed sudo)."
else
    echo "   warning: couldn't clear attributes. If you're in Downloads, move the"
    echo "   file to your Desktop, or grant Terminal Full Disk Access, and retry."
fi

echo "-> Making it executable..."
chmod +x "$BINARY" 2>/dev/null || sudo chmod +x "$BINARY" 2>/dev/null || true

echo
echo "Preparation complete. Now run it:"
echo "    ./$BINARY"
echo
echo "If macOS still shows a 'cannot be verified' popup:"
echo "  1. Click Done (never 'Move to Trash')."
echo "  2. Open System Settings > Privacy & Security, scroll to the bottom."
echo "  3. Click 'Open Anyway' next to the $BINARY message, then authenticate."
echo "  4. Run ./$BINARY again (sometimes you have to run it twice)."
echo
echo "After the first approval, future launches are smooth."
