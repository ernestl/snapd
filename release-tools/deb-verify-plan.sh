#!/bin/bash
# Discover Ubuntu series and per-series versions for a release pull request.
# Writes deb-verify-out/versions.json. Exits 0 and records a skipped report
# when the pull request head has moved on.

set -euo pipefail

: "${DEB_VERIFY_TOOL:?}"
: "${DEB_VERIFY_TREE:?}"
: "${DEB_VERIFY_OUT:?}"
: "${DEB_VERIFY_PR:?}"
: "${DEB_VERIFY_SHA:?}"
: "${DEB_VERIFY_RUN_ID:?}"
: "${DEB_VERIFY_HEAD_REPO:?}"
: "${DEB_VERIFY_REPO:?}"
: "${DEB_VERIFY_PPA:=snappy-dev/beta}"

mkdir -p "$DEB_VERIFY_OUT"

python3 "$DEB_VERIFY_TOOL" validate \
    --head-repo "$DEB_VERIFY_HEAD_REPO" \
    --head-sha "$DEB_VERIFY_SHA" \
    --pr "$DEB_VERIFY_PR" \
    --run-id "$DEB_VERIFY_RUN_ID" \
    --ppa "$DEB_VERIFY_PPA"

current=$(python3 "$DEB_VERIFY_TOOL" pr-head --repo "$DEB_VERIFY_REPO" --pr "$DEB_VERIFY_PR")
if [ "$current" != "$DEB_VERIFY_SHA" ]; then
    python3 "$DEB_VERIFY_TOOL" skipped-report \
        --reason "pull request head is ${current}" \
        --ppa "$DEB_VERIFY_PPA" \
        --write "$DEB_VERIFY_OUT/build-report.json" \
        --publications "$DEB_VERIFY_OUT/publications.json"
    echo "superseded=true" >> "$GITHUB_OUTPUT"
    echo "planned=false" >> "$GITHUB_OUTPUT"
    exit 0
fi

python3 "$DEB_VERIFY_TOOL" series --write "$DEB_VERIFY_OUT/series.json"
python3 "$DEB_VERIFY_TOOL" versions \
    --series "$DEB_VERIFY_OUT/series.json" \
    --tree "$DEB_VERIFY_TREE" \
    --pr "$DEB_VERIFY_PR" \
    --sha "$DEB_VERIFY_SHA" \
    --run-id "$DEB_VERIFY_RUN_ID" \
    --write "$DEB_VERIFY_OUT/versions.json"

echo "superseded=false" >> "$GITHUB_OUTPUT"
echo "planned=true" >> "$GITHUB_OUTPUT"
