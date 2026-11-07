# Guest

Everything that ends up inside the Pal VM (Debian 13 "trixie", arm64).

```
guest/
  agent/        pal-guest-agent: the VM's only link to the host and internet
  image/        builds the VM disk and cloud-init seed on the Mac
  provision/    first-boot provisioning that runs inside the VM
  system/       files installed into the VM
    systemd/system/ pal-guest-agent.service
    systemd/user/   pal-runtime.service, pal-display@.service
    bin/            pal-display-session, pal-display-save, pal-desktop-defaults
```

## Inside the VM

| Path | Contents |
| --- | --- |
| `/opt/pal/src` | a copy of this repository |
| `/opt/pal/venv` | the runtime's virtual environment (`pal` command) |
| `/opt/pal/bin` | display helper scripts |
| `/home/pal/.config/pal` | `pal.toml`, `bots/`, `secrets/`, per-display env files |
| `/home/pal/.local/share/pal` | memory, conversations, runtime state |
| `/home/pal/workspaces` | the bots' main folder |

The runtime and every display run as systemd **user** units of the `pal`
user, with lingering enabled so they start at boot without a login.

```sh
systemctl --user status pal-runtime
systemctl --user status 'pal-display@*'
journalctl --user -u pal-runtime -f
```
