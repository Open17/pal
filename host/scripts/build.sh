#!/usr/bin/env bash
# Build palvmd and palctl, sign palvmd with the virtualization entitlement,
# and install both into Pal's bin directory.
#
#   host/scripts/build.sh [--debug] [--install-dir DIR]
set -euo pipefail

host_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
configuration=release
install_dir="${PAL_HOME:-$HOME/Library/Application Support/Pal}/bin"

while [[ $# -gt 0 ]]; do
    case $1 in
        --debug) configuration=debug; shift ;;
        --install-dir) install_dir=$2; shift 2 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

cd "$host_dir"
swift build -c "$configuration" --product palvmd
swift build -c "$configuration" --product palctl
build_dir=$(swift build -c "$configuration" --show-bin-path)

mkdir -p "$install_dir"
install -m 0755 "$build_dir/palvmd" "$build_dir/palctl" "$install_dir/"
# Ad-hoc signature with the entitlement the hypervisor framework requires.
codesign --force --sign - --entitlements Resources/palvmd.entitlements "$install_dir/palvmd"
codesign --force --sign - "$install_dir/palctl"

echo "installed palvmd and palctl to $install_dir"
echo "add it to your PATH, e.g.: export PATH=\"$install_dir:\$PATH\""
