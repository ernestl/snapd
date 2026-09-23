#!/bin/bash
# Build unsigned snapd source packages for the versions in versions.json.
#
# For each packaging variant this commits a local debian symlink (the
# top-level debian path is gitignored, so the add is forced) and runs
# gbp buildpackage -S. Each target series then gets its own changelog
# header and dpkg-buildpackage -S.

set -euo pipefail

: "${DEB_VERIFY_TOOL:?}"
: "${DEB_VERIFY_TREE:?}"
: "${DEB_VERIFY_OUT:?}"

DEB_VERIFY_TREE=$(cd "$DEB_VERIFY_TREE" && pwd)
versions="$DEB_VERIFY_OUT/versions.json"
sources="$DEB_VERIFY_OUT/sources.json"
rm -f "$sources"
mkdir -p "$DEB_VERIFY_OUT/pkg"

export GIT_CONFIG_GLOBAL="$DEB_VERIFY_OUT/gitconfig"
git config --file "$GIT_CONFIG_GLOBAL" --add safe.directory '*'
git config --file "$GIT_CONFIG_GLOBAL" user.email "snapd-deb-verify@canonical.com"
git config --file "$GIT_CONFIG_GLOBAL" user.name "snapd deb verify"

on_err() {
    status=$?
    trap - ERR
    echo "deb-verify-sources failed with status ${status}" >&2
    python3 "$DEB_VERIFY_TOOL" append-source \
        --report "$sources" \
        --packaging script \
        --error "source script exited ${status}" || true
    exit "$status"
}
trap on_err ERR

field() {
    python3 -c 'import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])' "$1" "$2"
}

build_series() {
    local packaging="$1"
    local series="$2"
    local version="$3"
    local tree="$4"
    local dest="$DEB_VERIFY_OUT/pkg/${series}"
    local log="$DEB_VERIFY_OUT/${series}-source.log"

    rm -rf "$dest"
    mkdir -p "$dest"
    cp -a "$tree" "$dest/src"
    python3 "$DEB_VERIFY_TOOL" rewrite-changelog \
        "$dest/src/debian/changelog" \
        --version "$version" \
        --distribution "$series"

    local status=0
    set +e
    (cd "$dest/src" && dpkg-buildpackage -S -uc -us -d) >"$log" 2>&1
    status=$?
    set -e
    if [ "$status" -ne 0 ]; then
        python3 "$DEB_VERIFY_TOOL" append-source \
            --report "$sources" \
            --packaging "$packaging" \
            --series "$series" \
            --error-file "$log"
        return 1
    fi
    python3 "$DEB_VERIFY_TOOL" append-source \
        --report "$sources" \
        --packaging "$packaging" \
        --series "$series" \
        --ok
}

build_packaging() {
    local packaging="$1"
    local work="$DEB_VERIFY_OUT/work-${packaging}"
    local log="$DEB_VERIFY_OUT/${packaging}-gbp.log"
    local upstream=""
    local line=""

    rm -rf "$work"
    mkdir -p "$work"
    git clone --local "$DEB_VERIFY_TREE" "$work/src"

    if [ -e "$work/src/debian" ] && [ ! -L "$work/src/debian" ]; then
        python3 "$DEB_VERIFY_TOOL" append-source \
            --report "$sources" \
            --packaging "$packaging" \
            --error "debian exists and is not a symlink"
        return 1
    fi
    ln -sfn "packaging/${packaging}" "$work/src/debian"
    git -C "$work/src" add -f debian
    git -C "$work/src" commit -m "debian symlink for ${packaging}"

    local status=0
    set +e
    (cd "$work/src" && gbp buildpackage -S --git-ignore-branch --git-no-purge --git-ignore-new -us -uc) >"$log" 2>&1
    status=$?
    set -e
    if [ "$status" -ne 0 ]; then
        python3 "$DEB_VERIFY_TOOL" append-source \
            --report "$sources" \
            --packaging "$packaging" \
            --error-file "$log"
        return 1
    fi

    while IFS= read -r line; do
        if [ "$(field "$line" packaging)" = "$packaging" ]; then
            upstream=$(field "$line" upstream)
            break
        fi
    done < <(python3 "$DEB_VERIFY_TOOL" list-versions --versions "$versions")

    local tree="$work/build-area/snapd-${upstream}"
    if [ ! -d "$tree" ]; then
        tree=$(find "$work/build-area" -maxdepth 3 -type d -name 'snapd-*' | head -n 1 || true)
    fi
    if [ -z "$tree" ] || [ ! -d "$tree" ]; then
        python3 "$DEB_VERIFY_TOOL" append-source \
            --report "$sources" \
            --packaging "$packaging" \
            --error "gbp did not leave an unpacked source tree"
        return 1
    fi

    local series_failed=0
    while IFS= read -r line; do
        if [ "$(field "$line" packaging)" != "$packaging" ]; then
            continue
        fi
        if ! build_series "$packaging" "$(field "$line" series)" "$(field "$line" version)" "$tree"; then
            series_failed=1
        fi
    done < <(python3 "$DEB_VERIFY_TOOL" list-versions --versions "$versions")
    return "$series_failed"
}

mapfile -t packagings < <(python3 "$DEB_VERIFY_TOOL" packagings --versions "$versions")
if [ "${#packagings[@]}" -eq 0 ]; then
    python3 "$DEB_VERIFY_TOOL" append-source \
        --report "$sources" \
        --packaging none \
        --error "no Ubuntu series to package"
    exit 1
fi

failed=0
for packaging in "${packagings[@]}"; do
    if ! build_packaging "$packaging"; then
        failed=1
    fi
done

trap - ERR
if [ "$failed" -ne 0 ]; then
    exit 1
fi
