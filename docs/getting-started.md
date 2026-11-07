# Getting started

Pal runs on a Mac with Apple silicon (macOS 14 or later). You need the Xcode
command line tools (`xcode-select --install`) and a network connection for
the first build.

## 1. Build the host tools

```sh
host/scripts/build.sh
export PATH="$HOME/Library/Application Support/Pal/bin:$PATH"
```

This builds `palvmd` (the VM daemon) and `palctl` (its command-line control),
signs `palvmd` with the virtualization entitlement, and installs both to
`~/Library/Application Support/Pal/bin`.

## 2. Create a sign-in token

Pal's bots use your signed-in Claude account, not an API key. Create a
long-lived token on the Mac and save it to a file:

```sh
claude setup-token > ~/pal-token.txt
```

You can skip this and sign in inside the VM later instead (step 5).

## 3. Build the VM

```sh
guest/image/build-image.sh --oauth-token-file ~/pal-token.txt
rm ~/pal-token.txt
```

The builder downloads and verifies the Debian 13 arm64 cloud image, creates a
64 GiB sparse disk, generates the VM's secrets (API token, VNC password, SSH
key), and writes everything to `~/Library/Application Support/Pal/vm`. Useful
options: `--cpus`, `--memory` (MiB), `--disk-size` (GiB), `--no-sudo`.

## 4. Turn it on

```sh
palctl start
```

The VM keeps running in the background — after you close the terminal, and
after a palvmd crash — until you turn it off with `palctl stop`. If it is on
when you log out, it comes back when you log in.

The first boot provisions the guest: it upgrades to the latest Debian 13 point
release, installs the xfce4 desktop and the Pal runtime, and starts the bots.
That takes several minutes. Follow along with:

```sh
palctl ssh sudo tail -f /var/log/pal-provision.log
```

## 5. Talk to the bots

From inside the VM:

```sh
palctl ssh
pal status
pal chat atlas
```

If you skipped the token in step 2, sign in once inside the VM, then restart
the runtime:

```sh
claude login
systemctl --user restart pal-runtime
```

The runtime API listens on port 8765 of the VM's address
(`palctl address`). Requests need the token in
`~/Library/Application Support/Pal/vm/secrets/api-token`:

```sh
curl -H "Authorization: Bearer $(cat ~/Library/Application\ Support/Pal/vm/secrets/api-token)" \
    "http://$(palctl address):8765/v1/status"
```

## 6. Watch a bot's display

Each bot has its own display, served over VNC on the VM's address:

| Display | Owner | VNC port |
| --- | --- | --- |
| `:1` | you (operator) | 5901 |
| `:10`, `:11`, … | bots, in alphabetical order of their ids | 5910, 5911, … |

The VNC password is in `~/Library/Application Support/Pal/vm/secrets/vnc-password`.
Connecting wakes the display if it is asleep; it stays awake while you watch.

## Changing models

Every bot defaults to `claude-sonnet-5-5` at `high` effort. Change the default
or a single bot at runtime through the API:

```sh
# all bots
curl -X PATCH -d '{"effort": "medium"}' .../v1/settings
# one bot
curl -X PATCH -d '{"model": "claude-opus-5-5", "effort": "max"}' .../v1/bots/forge
```

Or set them permanently in `~/.config/pal/pal.toml` and `~/.config/pal/bots/<id>.toml`
inside the VM.

## Rebuilding

- `guest/image/build-image.sh --refresh-seed` re-provisions the existing VM on
  its next boot (for example, to pick up a new runtime). Data is kept.
- `guest/image/build-image.sh --force` replaces the disk. **All VM data is lost.**
