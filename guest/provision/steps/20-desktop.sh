# Lightweight xfce4 desktop served over VNC. No display manager: each
# display is started on demand by the runtime.

apt_install \
    xfce4 xfce4-terminal thunar mousepad \
    tigervnc-standalone-server tigervnc-tools \
    dbus-x11 at-spi2-core \
    x11-xserver-utils x11-utils xdotool wmctrl \
    fonts-dejavu fonts-noto-core fonts-noto-color-emoji adwaita-icon-theme \
    firefox-esr

# Never start a graphical login on the VM's own (nonexistent) console.
systemctl set-default multi-user.target

# Pal's desktop settings are applied per session by pal-desktop-defaults.
# Earlier guests replaced the packaged xfconf defaults, which removed the
# default session definition; restore the packaged files if so.
xfconf_dir=/etc/xdg/xfce4/xfconf/xfce-perchannel-xml
for file in "$xfconf_dir"/*.xml; do
    [[ -f $file ]] && grep -q "Pal defaults" "$file" || continue
    package=$(dpkg -S "$file" 2>/dev/null | cut -d: -f1 || true)
    rm -f "$file"
    if [[ -n $package ]]; then
        log "restoring $file from $package"
        apt-get install -y --reinstall -o Dpkg::Options::=--force-confmiss "$package"
    fi
done

# Screen lockers would lock bots out of their own displays.
apt-get purge -y light-locker xfce4-screensaver xscreensaver 2>/dev/null || true
