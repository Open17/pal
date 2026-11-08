# The pal user: folders, configuration, and secrets.

id "$PAL_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$PAL_USER"

if [[ ${PAL_GRANT_SUDO:-true} == true ]]; then
    # The VM is the bots' own computer; let them install software.
    printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$PAL_USER" >/etc/sudoers.d/90-pal
    chmod 0440 /etc/sudoers.d/90-pal
else
    rm -f /etc/sudoers.d/90-pal
fi

# Create the XDG parents first: install -d would otherwise make them owned by
# root, and the desktop and user services could not write their settings.
for dir in "$PAL_HOME/.config" "$PAL_HOME/.local" "$PAL_HOME/.local/share"; do
    install -d -o "$PAL_USER" -g "$PAL_USER" "$dir"
    chown "$PAL_USER:$PAL_USER" "$dir"
done

for dir in "$PAL_CONFIG" "$PAL_CONFIG/bots" "$PAL_CONFIG/displays" "$PAL_DATA" \
    "$PAL_WORKSPACES"; do
    install -d -o "$PAL_USER" -g "$PAL_USER" "$dir"
done
install -d -m 0700 -o "$PAL_USER" -g "$PAL_USER" "$PAL_CONFIG/secrets"

# Configuration is installed once; later edits inside the VM are kept.
[[ -f $PAL_CONFIG/pal.toml ]] || install_as_pal 0644 "$PAL_SRC/config/pal.toml" "$PAL_CONFIG/pal.toml"
# The starter bot only goes into an empty team: bots are added and removed
# from the app, and a removed one must stay removed.
if ! compgen -G "$PAL_CONFIG/bots/*.toml" >/dev/null; then
    for bot in "$PAL_SRC"/config/bots/*.toml; do
        install_as_pal 0644 "$bot" "$PAL_CONFIG/bots/$(basename "$bot")"
    done
fi

# Secrets staged by the image builder.
secrets_in=$PROVISION_DIR/secrets
for name in api-token oauth-token; do
    if [[ -s $secrets_in/$name ]]; then
        install_as_pal 0600 "$secrets_in/$name" "$PAL_CONFIG/secrets/$name"
    fi
done
if [[ -s $secrets_in/vnc-password ]]; then
    tr -d '\n' <"$secrets_in/vnc-password" | vncpasswd -f >"$PAL_CONFIG/secrets/vnc-passwd"
    chown "$PAL_USER:$PAL_USER" "$PAL_CONFIG/secrets/vnc-passwd"
    chmod 0600 "$PAL_CONFIG/secrets/vnc-passwd"
elif [[ ! -s $PAL_CONFIG/secrets/vnc-passwd ]]; then
    warn "no VNC password provisioned; displays will refuse viewers"
fi
