# Systemd user units for the pal user, started at boot via lingering.

install -d /etc/systemd/user
install -m 0644 "$PAL_SRC"/guest/system/systemd/user/*.service /etc/systemd/user/

loginctl enable-linger "$PAL_USER"
uid=$(pal_uid)
for _ in $(seq 1 50); do
    [[ -S /run/user/$uid/bus ]] && break
    sleep 0.2
done

as_pal systemctl --user daemon-reload
as_pal systemctl --user enable pal-runtime.service
as_pal systemctl --user restart pal-runtime.service
