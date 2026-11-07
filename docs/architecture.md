# Architecture

Pal has three layers: the macOS **host**, the Linux **guest** VM, and the
**runtime** that runs inside the guest. The macOS app (not yet built) sits on
top of the host and talks to both the host daemon and the runtime API.

```
┌──────────────────────────── macOS (Apple Silicon) ────────────────────────────┐
│                                                                               │
│   Pal.app (future)  ──unix socket──▶  palvmd (launchd agent)                  │
│        │                               └─ hypervisor framework VM             │
│        │ HTTP + WebSocket (API)                                               │
│        │ VNC (per-display)                                                    │
│        ▼                                                                      │
│  ┌──────────────────────── Debian 13 guest (headless) ─────────────────────┐  │
│  │                                                                         │  │
│  │  pal-runtime (systemd user service)                                     │  │
│  │   ├─ API server ............ REST + event stream for the app            │  │
│  │   ├─ Bot team .............. one agent SDK session per bot              │  │
│  │   ├─ Messaging ............. user ⇄ bot and bot ⇄ bot, persisted        │  │
│  │   ├─ Memory ................ shared + per-bot knowledge (markdown files)  │  │
│  │   ├─ Tool registry ......... in-process tools exposed to bots           │  │
│  │   └─ Display manager ....... on-demand displays, idle sleep, VNC proxy  │  │
│  │                                                                         │  │
│  │  pal-display@<owner> (systemd user units)                               │  │
│  │   └─ Xvnc :N  +  xfce4-session        (one per bot, plus "operator")    │  │
│  │                                                                         │  │
│  │  ~/workspaces/<bot>/   each bot's main folder                           │  │
│  │  ~/workspaces/shared/  files every bot can see                          │  │
│  └─────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────────┘
```

## Host (`host/`)

- **`palvmd`** owns the virtual machine. It boots the guest disk through EFI,
  attaches a NAT network interface, an entropy device, a memory balloon, and a
  serial console that is logged to disk. There is no virtual GPU: the desktop
  is served from inside the guest over VNC, which keeps the VM small.
- `palvmd` runs as a per-user launchd agent. Turning the VM **on** enables and
  bootstraps the agent; turning it **off** asks the guest to shut down cleanly,
  then disables the agent. Because launchd keeps the agent alive, the VM runs
  in the background indefinitely, survives the app quitting, and restarts after
  a crash — but stays off once you turn it off.
- `palvmd` exposes a small JSON control protocol over a Unix socket (`status`,
  `stop`, `address`). `palctl` is the command-line client; the app will use the
  same protocol through `PalVMKit`.

## Guest (`guest/`)

- The base image is the official Debian 13 `genericcloud` arm64 image. The
  image builder downloads and verifies it, grows the disk, and writes a
  cloud-init seed that carries the provisioning payload and generated secrets.
- On first boot, provisioning upgrades to the latest trixie point release,
  installs xfce4 and TigerVNC, creates the `pal` user, installs the runtime into
  a virtual environment, and enables the systemd units.

## Runtime (`runtime/`)

### Bots

Each bot is defined in `config/bots/<id>.toml` (name, role, persona, optional
model/effort override). The runtime keeps one agent SDK client per bot, with:

- **Model and effort** — defaults to `claude-sonnet-5-5` at `high` effort.
  Both can be changed globally or per bot at runtime through the API. A model
  change is applied live; an effort change reconnects the bot and resumes the
  same session, so the conversation is not lost.
- **Working directory** — `~/workspaces/<bot-id>/`, with `~/workspaces/shared/`
  added as an extra directory. Bots can still use the whole machine.
- **Session persistence** — each bot's session id is stored so conversations
  resume after the runtime or VM restarts.
- **Authentication** — a signed-in Claude account. The runtime passes an OAuth
  token (from `claude setup-token`) to the SDK if one is provisioned and never
  uses a developer API key; otherwise the SDK falls back to the login stored by
  an interactive `claude login` inside the VM.

### Messaging

Every exchange — user to bot, bot to bot — is a `Message` on the event bus and
is appended to a JSONL conversation log. Bots talk to each other with the
built-in `message_bot` tool:

- **Ask** (`wait_for_reply=true`): the calling bot blocks until the other bot
  answers, with a timeout. The runtime tracks the chain of waiting bots and
  refuses a request that would loop back to a bot that is already waiting,
  which prevents deadlocks.
- **Tell** (`wait_for_reply=false`): the message is queued in the recipient's
  inbox and handled after its current turn.

### Memory

Memory is a directory of markdown files with a small frontmatter header, so it
is durable, greppable, and readable by humans and bots alike.

- **Shared memory** (`memory/shared/`) — visible to every bot.
- **Bot knowledge** (`memory/bots/<id>/`) — private to one bot.

Bots read and write memory through built-in tools (`remember`, `recall`,
`forget`). An index of each bot's relevant memories is placed in its system
prompt when its session starts. Writes are atomic and file-locked.

### Displays

Each bot owns one X display (`Xvnc` running an `xfce4-session`), and there is an
`operator` display for you to remote-control the VM.

- **On demand.** A display is not started until its bot needs the computer:
  any tool that is marked as needing a display wakes it first, and bots can
  wake it explicitly before running graphical programs from the shell.
- **Idle sleep.** After 8 minutes without bot activity and with no viewer
  connected, the display is **frozen** (its cgroup is suspended). Frozen
  displays use no CPU but keep every window and process exactly as they were,
  so the bot — or you — comes back to the same screen.
- **Viewing.** Each display has a VNC endpoint behind a small proxy in the
  runtime. Connecting a viewer wakes the display and keeps it awake while the
  viewer is attached.
- **Restarts.** The runtime remembers which displays were running and brings
  them back after a reboot, and xfce session saving is enabled so session-aware
  applications reopen.

### Tools

The runtime has a tool registry. Each tool provider contributes in-process
tools to every bot's session and declares whether its tools need a display.
The built-in providers cover memory, messaging, and display control; custom
computer-control tools and integrations will be added as further providers.

### API

The app talks to the runtime over HTTP with a bearer token:

- REST endpoints for bots, settings (model/effort), conversations, memory, and
  displays.
- A WebSocket event stream with message, streaming-text, tool, bot-status, and
  display-state events.

## Data layout inside the guest

```
~/workspaces/                      bots' main folder
  shared/                          shared between all bots
  <bot-id>/                        one folder per bot (its working directory)
~/.config/pal/
  pal.toml                         runtime configuration
  bots/<bot-id>.toml               bot definitions
  secrets/                         api-token, vnc-password, oauth-token (0600)
~/.local/share/pal/
  memory/shared/*.md               shared long-term memory
  memory/bots/<bot-id>/*.md        private bot knowledge
  conversations/<id>.jsonl         message logs
  state/sessions.json              agent session ids per bot
  state/displays.json              display allocation and last-known state
```
