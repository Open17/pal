# Internet access through the host. Runs first: nothing else in provisioning
# can download anything until the guest agent is up.
#
# The VM has no network interface. The guest agent sends every connection to
# palvmd on the host over vsock, and palvmd connects only to the public
# internet — never to the host or its local network.

install -d /opt/pal/agent
install -m 0755 "$PAL_SRC/guest/agent/pal_guest_agent.py" /opt/pal/agent/
install -m 0644 "$PAL_SRC/guest/system/systemd/system/pal-guest-agent.service" /etc/systemd/system/

# These expect a real network interface and would only wait or fail; the
# agent provides name resolution and keeps the clock in step with the host.
for unit in systemd-resolved.service systemd-timesyncd.service systemd-networkd-wait-online.service; do
    systemctl disable --now "$unit" 2>/dev/null || true
    systemctl mask "$unit" 2>/dev/null || true
done

systemctl daemon-reload
systemctl enable pal-guest-agent.service
# The unit refuses manual stops (and so restarts); on re-provisioning, end the
# running agent and let systemd start the new one.
if systemctl is-active --quiet pal-guest-agent.service; then
    systemctl kill pal-guest-agent.service
    sleep 2
fi
systemctl start pal-guest-agent.service

for _ in $(seq 1 30); do
    getent ahostsv4 deb.debian.org >/dev/null && break
    sleep 1
done
getent ahostsv4 deb.debian.org >/dev/null ||
    die "no internet access through the host (is palvmd running with its egress service?)"
log "internet access through the host is working"
