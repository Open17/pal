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

# Desktop defaults for every display.
install -d /etc/xdg/xfce4/xfconf/xfce-perchannel-xml
install -m 0644 "$PAL_SRC"/guest/system/xfce/xfconf/xfce-perchannel-xml/*.xml \
    /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/

# Screen lockers would lock bots out of their own displays.
apt-get purge -y light-locker xfce4-screensaver xscreensaver 2>/dev/null || true
