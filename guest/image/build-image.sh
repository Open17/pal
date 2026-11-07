#!/usr/bin/env bash
# Build the Pal VM on the Mac: disk image, cloud-init seed, secrets, and the
# VM configuration read by palvmd.
#
#   guest/image/build-image.sh [options]
#
# Options:
#   --vm-dir DIR            where the VM lives (default: ~/Library/Application Support/Pal/vm)
#   --disk-size SIZE        virtual disk size in GiB (default: 64)
#   --cpus N                virtual CPUs (default: 4)
#   --memory MIB            memory in MiB (default: a quarter of this Mac's memory, 2048-8192)
#   --oauth-token-file F    sign-in token from `claude setup-token` (or set PAL_OAUTH_TOKEN)
#   --no-sudo               do not give the pal user passwordless sudo
#   --force                 replace an existing disk (the VM's data is lost)
#   --refresh-seed          only rebuild the seed and payload (re-provisions on next boot)
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
image_dir="$repo_root/guest/image"

base_url=${PAL_DEBIAN_IMAGE_BASE:-https://cloud.debian.org/images/cloud/trixie/latest}
image_name=debian-13-genericcloud-arm64
min_debian=${PAL_MIN_DEBIAN_VERSION:-13.7}

vm_dir="$HOME/Library/Application Support/Pal/vm"
disk_gib=64
cpus=4
# A quarter of the Mac's memory leaves the host plenty of room.
memory_mib=$(( $(sysctl -n hw.memsize) / 1048576 / 4 ))
(( memory_mib < 2048 )) && memory_mib=2048
(( memory_mib > 8192 )) && memory_mib=8192
oauth_token_file=""
grant_sudo=true
force=false
seed_only=false

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
log() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case $1 in
        --vm-dir) vm_dir=$2; shift 2 ;;
        --disk-size) disk_gib=$2; shift 2 ;;
        --cpus) cpus=$2; shift 2 ;;
        --memory) memory_mib=$2; shift 2 ;;
        --oauth-token-file) oauth_token_file=$2; shift 2 ;;
        --no-sudo) grant_sudo=false; shift ;;
        --force) force=true; shift ;;
        --refresh-seed) seed_only=true; shift ;;
        -h | --help) usage ;;
        *) printf 'unknown option: %s\n\n' "$1" >&2; usage 2 ;;
    esac
done

[[ $(uname -s) == Darwin && $(uname -m) == arm64 ]] || die "Pal's VM requires a Mac with Apple silicon"
for tool in curl shasum tar hdiutil ssh-keygen openssl python3; do
    command -v "$tool" >/dev/null || die "missing required tool: $tool"
done
[[ $disk_gib =~ ^[0-9]+$ && $disk_gib -ge 16 ]] || die "--disk-size must be at least 16 (GiB)"

# Rebuilding under a running VM would swap its disk or seed out from under it.
socket="$(dirname "$vm_dir")/run/palvmd.sock"
if [[ -S $socket ]] && python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect(sys.argv[1])' "$socket" 2>/dev/null; then
    die "the VM is running; turn it off first (palctl stop)"
fi

cache_dir="$vm_dir/cache"
secrets_dir="$vm_dir/secrets"
disk="$vm_dir/disk.img"
mkdir -p "$cache_dir"
install -d -m 0700 "$secrets_dir"

# -- secrets -------------------------------------------------------------------

random_token() { openssl rand -base64 48 | tr '+/' '-_' | tr -d '=\n' | cut -c1-"$1"; }

[[ -s $secrets_dir/api-token ]] || random_token 43 >"$secrets_dir/api-token"
# The VNC protocol's password authentication uses at most 8 characters.
[[ -s $secrets_dir/vnc-password ]] || random_token 8 >"$secrets_dir/vnc-password"
[[ -f $secrets_dir/id_ed25519 ]] ||
    ssh-keygen -q -t ed25519 -N "" -C "pal-host" -f "$secrets_dir/id_ed25519"

if [[ -n $oauth_token_file ]]; then
    tr -d '[:space:]' <"$oauth_token_file" >"$secrets_dir/oauth-token"
elif [[ -n ${PAL_OAUTH_TOKEN:-} ]]; then
    printf '%s' "$PAL_OAUTH_TOKEN" >"$secrets_dir/oauth-token"
fi
chmod 0600 "$secrets_dir"/*

# -- disk ----------------------------------------------------------------------

if [[ $seed_only == false ]]; then
    if [[ -f $disk && $force == false ]]; then
        die "$disk already exists; use --force to replace it or --refresh-seed to re-provision"
    fi

    archive="$cache_dir/$image_name.tar.xz"
    log "fetching checksums"
    curl -fsSL "$base_url/SHA512SUMS" -o "$cache_dir/SHA512SUMS"
    expected=$(awk -v f="$image_name.tar.xz" '$2 == f { print $1 }' "$cache_dir/SHA512SUMS")
    [[ -n $expected ]] || die "no checksum for $image_name.tar.xz"

    if [[ ! -f $archive ]] || ! echo "$expected  $archive" | shasum -a 512 -c --status; then
        log "downloading $image_name.tar.xz"
        curl -fL --progress-bar "$base_url/$image_name.tar.xz" -o "$archive.partial"
        mv "$archive.partial" "$archive"
    fi
    echo "$expected  $archive" | shasum -a 512 -c --status || die "checksum mismatch for $archive"
    log "base image verified"

    work=$(mktemp -d "$cache_dir/extract.XXXXXX")
    trap 'rm -rf "$work"' EXIT
    tar -xJSf "$archive" -C "$work" disk.raw
    log "growing disk to ${disk_gib} GiB"
    python3 -c 'import os, sys; os.truncate(sys.argv[1], int(sys.argv[2]) << 30)' \
        "$work/disk.raw" "$disk_gib"
    mv -f "$work/disk.raw" "$disk"
    # A new disk needs a fresh firmware store and machine identity, and it
    # generates new SSH host keys, so forget the old ones.
    rm -f "$vm_dir/efi-vars.fd" "$vm_dir/machine-id" "$vm_dir/known_hosts"
fi
[[ -f $disk ]] || die "no disk at $disk; run without --refresh-seed first"

# -- seed ----------------------------------------------------------------------

log "packing provisioning payload"
payload="$cache_dir/payload.tar.gz"
COPYFILE_DISABLE=1 tar --no-xattrs -czf "$payload" -C "$repo_root" \
    --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
    --exclude '.ruff_cache' --exclude '*.egg-info' --exclude '.DS_Store' \
    README.md docs config runtime guest

seed_dir=$(mktemp -d "$cache_dir/seed.XXXXXX")
python3 "$image_dir/render-seed.py" "$seed_dir" \
    --payload "$payload" \
    --secrets "$secrets_dir" \
    --env "PAL_MIN_DEBIAN_VERSION=$min_debian" \
    --env "PAL_GRANT_SUDO=$grant_sudo" \
    --env "PAL_TIMEZONE=$(readlink /etc/localtime | sed 's|.*/zoneinfo/||')"

log "writing cloud-init seed"
rm -f "$vm_dir/seed.iso"
hdiutil makehybrid -quiet -iso -joliet -default-volume-name cidata \
    -o "$vm_dir/seed.iso" "$seed_dir"
rm -rf "$seed_dir"

# -- VM configuration ------------------------------------------------------------

# The guest has no network interface; palvmd forwards its SSH, API, and VNC
# ports to 127.0.0.1 on this Mac (see PortForward.defaults in host/).
config="$vm_dir/config.json"
cat >"$config" <<JSON
{
  "version": 2,
  "cpuCount": $cpus,
  "memorySizeMiB": $memory_mib,
  "diskImage": "disk.img",
  "seedImage": "seed.iso",
  "efiVariableStore": "efi-vars.fd",
  "machineIdentifier": "machine-id",
  "consoleLog": "console.log"
}
JSON

log "VM ready in $vm_dir"
if [[ ! -s $secrets_dir/oauth-token ]]; then
    echo "    note: no sign-in token given. Run 'claude setup-token' and rebuild with"
    echo "    --refresh-seed --oauth-token-file FILE, or sign in inside the VM later."
fi
echo "    start it with: palctl start"
