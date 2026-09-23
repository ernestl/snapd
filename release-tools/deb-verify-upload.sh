#!/bin/bash
# Sign source packages and upload them to the snappy-dev beta PPA.
# Stops before signing when the pull request head is no longer current.

set -euo pipefail

: "${DEB_VERIFY_TOOL:?}"
: "${DEB_VERIFY_OUT:?}"
: "${DEB_VERIFY_PR:?}"
: "${DEB_VERIFY_SHA:?}"
: "${DEB_VERIFY_REPO:?}"
: "${DEB_VERIFY_PPA:?}"

versions="$DEB_VERIFY_OUT/versions.json"
report="$DEB_VERIFY_OUT/uploads.json"
rm -f "$report"

materialize_secret() {
    local raw="$1"
    local dest="$2"
    if printf '%s\n' "$raw" | grep -q -- "-----BEGIN"; then
        printf '%s\n' "$raw" > "$dest"
    else
        printf '%s' "$raw" | tr -d '\n' | base64 -d > "$dest"
    fi
    chmod 600 "$dest"
}

current=$(python3 "$DEB_VERIFY_TOOL" pr-head --repo "$DEB_VERIFY_REPO" --pr "$DEB_VERIFY_PR")
if [ "$current" != "$DEB_VERIFY_SHA" ]; then
    python3 "$DEB_VERIFY_TOOL" skipped-report \
        --reason "pull request head is ${current}" \
        --ppa "$DEB_VERIFY_PPA" \
        --write "$DEB_VERIFY_OUT/build-report.json" \
        --publications "$DEB_VERIFY_OUT/publications.json"
    echo "superseded=true" >> "$GITHUB_OUTPUT"
    echo "any_ok=false" >> "$GITHUB_OUTPUT"
    exit 0
fi
echo "superseded=false" >> "$GITHUB_OUTPUT"

on_err() {
    status=$?
    trap - ERR
    echo "deb-verify-upload failed with status ${status}" >&2
    if [ ! -s "$report" ]; then
        python3 "$DEB_VERIFY_TOOL" append-upload \
            --report "$report" \
            --series "-" \
            --version "-" \
            --error "upload script exited ${status}" || true
    fi
    if [ -n "${GITHUB_OUTPUT:-}" ]; then
        echo "any_ok=false" >> "$GITHUB_OUTPUT"
    fi
    exit "$status"
}
trap on_err ERR

: "${SNAPD_LP_USERNAME:?}"
: "${SNAPD_LP_SSH_KEY:?}"
: "${SNAPD_LP_GPG_PRIVATE_KEY:?}"
: "${SNAPD_LP_GPG_KEY_ID:?}"

install -d -m 700 "$HOME/.ssh" "$HOME/.gnupg"
materialize_secret "$SNAPD_LP_SSH_KEY" "$HOME/.ssh/id_launchpad"
materialize_secret "$SNAPD_LP_GPG_PRIVATE_KEY" "$HOME/.gnupg/snapd-key.asc"
gpg --batch --import "$HOME/.gnupg/snapd-key.asc"
rm -f "$HOME/.gnupg/snapd-key.asc"
printf '%s\n' "batch" "pinentry-mode loopback" >> "$HOME/.gnupg/gpg.conf"
chmod 700 "$HOME/.gnupg"

ssh-keyscan -H ppa.launchpad.net >> "$HOME/.ssh/known_hosts"
cat > "$HOME/.ssh/config" << EOF
Host ppa.launchpad.net
    IdentityFile ~/.ssh/id_launchpad
    IdentitiesOnly yes
EOF
chmod 600 "$HOME/.ssh/config"

owner=${DEB_VERIFY_PPA%%/*}
archive=${DEB_VERIFY_PPA#*/}
cat > "$HOME/.dput.cf" << EOF
[DEFAULT]
allow_unsigned_uploads = 0
run_lintian = 0

[snappy-beta]
fqdn = ppa.launchpad.net
method = sftp
incoming = ~${owner}/ubuntu/${archive}
login = ${SNAPD_LP_USERNAME}
allow_unsigned_uploads = 0
EOF

field() {
    python3 -c 'import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])' "$1" "$2"
}

failed=0
while IFS= read -r line; do
    series=$(field "$line" series)
    version=$(field "$line" version)
    changes=$(find "$DEB_VERIFY_OUT/pkg/${series}" -maxdepth 1 -name '*_source.changes' -print -quit || true)
    log="$DEB_VERIFY_OUT/upload-${series}.log"
    if [ -z "$changes" ]; then
        python3 "$DEB_VERIFY_TOOL" append-upload \
            --report "$report" \
            --series "$series" \
            --version "$version" \
            --error "source changes file is missing"
        failed=1
        continue
    fi
    status=0
    set +e
    (
        cd "$(dirname "$changes")"
        debsign -k "$SNAPD_LP_GPG_KEY_ID" "$(basename "$changes")"
        dput snappy-beta "$(basename "$changes")"
    ) >"$log" 2>&1
    status=$?
    set -e
    if [ "$status" -ne 0 ]; then
        python3 "$DEB_VERIFY_TOOL" append-upload \
            --report "$report" \
            --series "$series" \
            --version "$version" \
            --error-file "$log"
        failed=1
    else
        python3 "$DEB_VERIFY_TOOL" append-upload \
            --report "$report" \
            --series "$series" \
            --version "$version" \
            --ok
    fi
done < <(python3 "$DEB_VERIFY_TOOL" list-versions --versions "$versions")

if [ ! -s "$report" ]; then
    python3 "$DEB_VERIFY_TOOL" append-upload \
        --report "$report" \
        --series "-" \
        --version "-" \
        --error "no source packages to upload"
    failed=1
fi

trap - ERR

if [ -f "$report" ] && python3 -c 'import json,sys; rows=json.load(open(sys.argv[1])); raise SystemExit(0 if any(item.get("ok") for item in rows) else 1)' "$report"; then
    echo "any_ok=true" >> "$GITHUB_OUTPUT"
else
    echo "any_ok=false" >> "$GITHUB_OUTPUT"
fi

if [ "$failed" -ne 0 ]; then
    exit 1
fi
