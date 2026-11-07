# Base system: latest trixie point release, base packages, host identity.

min_debian=${PAL_MIN_DEBIAN_VERSION:-13.7}

log "upgrading to the latest Debian 13 point release"
apt-get update
apt-get -y -o Dpkg::Options::=--force-confold full-upgrade

debian_version=$(cat /etc/debian_version)
log "Debian version: $debian_version"
if ! version_ge "$debian_version" "$min_debian"; then
    warn "Debian $debian_version is older than $min_debian; check the configured mirrors"
fi

apt_install \
    ca-certificates curl git jq unzip sudo locales tzdata \
    python3 python3-venv python3-pip build-essential \
    dbus dbus-user-session openssh-server

hostnamectl set-hostname "${PAL_HOSTNAME:-pal}" || true
if [[ -n ${PAL_TIMEZONE:-} ]]; then
    timedatectl set-timezone "$PAL_TIMEZONE" || warn "unknown timezone $PAL_TIMEZONE"
fi
if ! locale -a 2>/dev/null | grep -qi '^en_US.utf8$'; then
    sed -i 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
    locale-gen
fi
update-locale LANG=en_US.UTF-8
