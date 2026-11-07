#!/usr/bin/env bash
# Shared helpers for provisioning steps. Sourced, not executed.

PAL_USER=${PAL_USER:-pal}
PAL_HOME=/home/$PAL_USER
PAL_ROOT=/opt/pal
PAL_SRC=$PAL_ROOT/src
PAL_VENV=$PAL_ROOT/venv
PAL_CONFIG=$PAL_HOME/.config/pal
PAL_DATA=$PAL_HOME/.local/share/pal
PAL_WORKSPACES=$PAL_HOME/workspaces
PROVISION_DIR=${PROVISION_DIR:-/var/lib/pal-provision}

export DEBIAN_FRONTEND=noninteractive

log() { printf '[pal-provision] %s\n' "$*"; }
warn() { printf '[pal-provision] WARNING: %s\n' "$*" >&2; }
die() { printf '[pal-provision] ERROR: %s\n' "$*" >&2; exit 1; }

require_root() { [[ $EUID -eq 0 ]] || die "must run as root"; }

apt_install() {
    apt-get install -y --no-install-recommends "$@"
}

pal_uid() { id -u "$PAL_USER"; }

# Run a command as the pal user with its systemd user manager reachable.
as_pal() {
    local uid
    uid=$(pal_uid)
    runuser -u "$PAL_USER" -- env \
        HOME="$PAL_HOME" \
        XDG_RUNTIME_DIR="/run/user/$uid" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
        "$@"
}

# Install a file owned by pal, creating parent directories.
install_as_pal() {
    local mode=$1 source=$2 target=$3
    install -d -o "$PAL_USER" -g "$PAL_USER" "$(dirname "$target")"
    install -m "$mode" -o "$PAL_USER" -g "$PAL_USER" "$source" "$target"
}

# Compare dotted versions: version_ge 13.7 13.4 -> true
version_ge() {
    [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]
}
