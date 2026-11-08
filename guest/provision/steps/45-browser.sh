# Chromium is the web browser. Every way of starting a browser on a display
# (the chromium command, links, the panel's web browser button) runs
# pal-chromium, which opens that display owner's own Chromium: its own
# profile, so several displays can browse at once, and its own debugging port,
# through which the runtime drives it and carries logins between them all.

# Only one browser: a second one would keep logins of its own.
apt-get purge -y firefox-esr 2>/dev/null || true

launcher=$PAL_ROOT/bin/pal-chromium
for name in pal-chromium chromium chromium-browser google-chrome firefox firefox-esr; do
    ln -sf "$launcher" "/usr/local/bin/$name"
done
for alternative in x-www-browser gnome-www-browser; do
    update-alternatives --install "/usr/bin/$alternative" "$alternative" "$launcher" 300
    update-alternatives --set "$alternative" "$launcher"
done

# The packaged menu entry starts /usr/bin/chromium by its full path, which
# would skip the launcher; this one takes its place.
install -d /usr/local/share/applications
sed "s|^Exec=/usr/bin/chromium|Exec=$launcher|" /usr/share/applications/chromium.desktop \
    >/usr/local/share/applications/chromium.desktop
update-desktop-database /usr/local/share/applications 2>/dev/null || true

cat >/etc/xdg/mimeapps.list <<'MIME'
[Default Applications]
text/html=chromium.desktop
application/xhtml+xml=chromium.desktop
x-scheme-handler/http=chromium.desktop
x-scheme-handler/https=chromium.desktop
MIME

# The address bar searches with the engine the user chose, and a browser
# reopens the windows and tabs it had. Policies apply to every profile.
install -d /etc/chromium/policies/managed
cat >/etc/chromium/policies/managed/pal.json <<'POLICY'
{
  "DefaultSearchProviderEnabled": true,
  "DefaultSearchProviderName": "Google",
  "DefaultSearchProviderKeyword": "google.com",
  "DefaultSearchProviderSearchURL": "https://www.google.com/search?q={searchTerms}",
  "DefaultSearchProviderSuggestURL": "https://www.google.com/complete/search?client=chrome&q={searchTerms}",
  "DefaultSearchProviderIconURL": "https://www.google.com/favicon.ico",
  "RestoreOnStartup": 1,
  "HomepageIsNewTabPage": true
}
POLICY

# Earlier guests ran one browser for everyone on a display of its own.
as_pal systemctl --user stop pal-display-browser.slice 2>/dev/null || true
rm -f "$PAL_CONFIG/displays/browser.env"

log "web browser: $(readlink -f /etc/alternatives/x-www-browser)"
