# Pal

Pal is a team of AI bots that live on their own computer. You can talk to any
bot, and the bots can talk to each other. Each bot has private knowledge, and
all bots share a long-term memory stored as plain files.

The bots run inside a lightweight Debian 13 (trixie) virtual machine with an
xfce4 desktop. Every bot gets its own display on that machine, which starts on
demand and sleeps after a period of inactivity without losing open windows. A
native macOS app (coming later) is the front end: it powers the VM on and off,
lets you chat with the bots, and lets you watch or remote-control any bot's
display.

## Repository layout

| Path | What lives there |
| --- | --- |
| [`host/`](host/) | macOS host side: the VM daemon (`palvmd`), its control CLI (`palctl`), and the `PalVMKit` library. Swift. |
| [`guest/`](guest/) | Everything that ends up inside the VM: image builder, provisioning scripts, systemd units, desktop defaults. |
| [`runtime/`](runtime/) | The Pal runtime that runs inside the VM: bots, memory, messaging, displays, and the API the app talks to. Python. |
| [`config/`](config/) | Default runtime configuration and bot definitions. |
| [`docs/`](docs/) | Architecture and contributor documentation. |

## Documentation

- [Architecture](docs/architecture.md)
- [Contributing and branching](docs/contributing.md)

## Status

Early development. Work lands on the `development` branch; `main` is reserved
for releases.


## License

OpenPal is licensed under the [OpenPal Personal Use Source-Available License](LICENSE.md).

You may inspect the source, run an unchanged copy for personal non-business use, and share unchanged copies for personal non-business use by others.
Modification, business use, and commercial distribution are not permitted.
Commercial rights are reserved to the copyright owner.
