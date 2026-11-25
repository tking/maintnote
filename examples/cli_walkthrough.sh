#!/usr/bin/env bash
# End-to-end walkthrough of the `maintnote` CLI using the sample fixtures.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAMPLES_DIR="${SCRIPT_DIR}/samples"

if [[ -n "${MAINTNOTE_CMD:-}" ]]; then
    read -r -a CLI <<< "${MAINTNOTE_CMD}"
elif command -v maintnote >/dev/null 2>&1; then
    CLI=(maintnote)
else
    CLI=(python3 -m maintnote.cli)
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

echo "=== 1. Validate sample initial notification (JSON) ==="
"${CLI[@]}" validate "${SAMPLES_DIR}/01_initial.ics" --json

echo ""
echo "=== 2. Parse multi-event CalDAV feed ==="
"${CLI[@]}" parse "${SAMPLES_DIR}/multi_event_feed.ics"

echo ""
echo "=== 3. Confirm invalid sample fails validation as expected ==="
if "${CLI[@]}" validate "${SAMPLES_DIR}/invalid_window.ics"; then
    echo "ERROR: expected invalid_window.ics to fail validation" >&2
    exit 1
else
    echo "(Validation rejected invalid_window.ics as expected)"
fi

echo ""
echo "=== 4. Strip METHOD from legacy .ics and .eml (Section 2.3.1) ==="
"${CLI[@]}" strip-method "${SAMPLES_DIR}/legacy_with_method.ics" > "${TMP_DIR}/sanitized.ics"
"${CLI[@]}" strip-email-method "${SAMPLES_DIR}/legacy_provider.eml" -o "${TMP_DIR}/sanitized.eml"
echo "Sanitized .ics and .eml written to ${TMP_DIR}"

echo ""
echo "=== 5. Extract notifications from .eml (JSON) ==="
"${CLI[@]}" extract-email "${SAMPLES_DIR}/legacy_provider.eml" --strip-method --json

echo ""
echo "=== 6. Generate full maintenance lifecycle via CLI ==="
"${CLI[@]}" generate --action initial \
    --provider example.com \
    --account CUST-42 \
    --maintenance-id WO-CLI-100 \
    --object-id "xe-0/0/0.fra1|https://example.org/objects/xe-0-0-0" \
    --impact OUTAGE \
    --summary "FRA1 edge router upgrade" \
    --organizer noc@example.com \
    --organizer-cn "Example NOC" \
    --dtstart 2026-12-01T02:00:00Z \
    --dtend 2026-12-01T04:00:00Z \
    -o "${TMP_DIR}/01_initial.ics"

"${CLI[@]}" generate --action confirm \
    --from-file "${TMP_DIR}/01_initial.ics" \
    --description "Window confirmed by engineering." \
    -o "${TMP_DIR}/02_confirmed.ics"

"${CLI[@]}" generate --action open \
    --from-file "${TMP_DIR}/02_confirmed.ics" \
    --description "Maintenance window is now open." \
    -o "${TMP_DIR}/03_open.ics"

"${CLI[@]}" generate --action close \
    --from-file "${TMP_DIR}/03_open.ics" \
    --description "Maintenance finished cleanly." \
    -o "${TMP_DIR}/04_closed.ics"

"${CLI[@]}" validate "${TMP_DIR}/04_closed.ics"
"${CLI[@]}" parse "${TMP_DIR}/04_closed.ics"
