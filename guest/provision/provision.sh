#!/usr/bin/env bash
# Provision a fresh Debian 13 VM into a Pal guest.
#
# Runs as root on first boot (from cloud-init) and can be re-run safely to
# repair or update an existing guest. Settings come from
# /var/lib/pal-provision/provision.env, written by the image builder.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
source "$here/lib.sh"
require_root

if [[ -f $PROVISION_DIR/provision.env ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROVISION_DIR/provision.env"
    set +a
fi

log_file=/var/log/pal-provision.log
exec > >(tee -a "$log_file") 2>&1
log "provisioning started $(date -Is)"

for step in "$here"/steps/[0-9][0-9]-*.sh; do
    log "==> $(basename "$step")"
    # shellcheck disable=SC1090
    source "$step"
done

date -Is >"$PROVISION_DIR/provisioned"
log "provisioning finished $(date -Is)"
