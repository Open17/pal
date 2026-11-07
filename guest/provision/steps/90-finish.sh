# Tidy up and report.

apt-get autoremove -y
apt-get clean

if [[ ! -s $PAL_CONFIG/secrets/oauth-token && ! -f $PAL_HOME/.claude/.credentials.json ]]; then
    warn "bots are not signed in yet: run 'claude setup-token' on the Mac and pass the token"
    warn "to the image builder, or run 'sudo -iu $PAL_USER claude login' inside the VM"
fi

log "runtime: $(as_pal systemctl --user is-active pal-runtime.service || true)"
log "Debian $(cat /etc/debian_version), $(uname -r)"
