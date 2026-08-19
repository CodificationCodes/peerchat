# Peer Chat

A terminal chat app. No account, no dedicated server required, anyone can
host a room from their own machine, or connect to a room someone else is
running.

## Install

### macOS / Linux

```bash
curl -sSL https://raw.githubusercontent.com/CodificationCodes/peerchat/main/install.sh | bash
```

Then run it from anywhere:

```bash
peerchat
```

The installer sets up an isolated environment automatically
(using `pipx` if you have it, or a dedicated virtual environment if not),
so it won't interfere with anything else on your system.

If `peerchat` is not found on macOS, add this to your shell profile
(`~/.zshrc` or `~/.bashrc`) and restart the terminal:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

If you want to run it immediately in the current terminal, run the same
`export PATH=...` line first, then start Peer Chat again.

### Windows (Command Prompt / PowerShell)

```powershell
git clone https://github.com/CodificationCodes/peerchat.git
cd peerchat
py -m pip install --user .
py -m peerchat
```

`py -m peerchat` works even if your Python Scripts folder is not on PATH.
If you want to run just `peerchat`, add your user Scripts folder to PATH.

### Manual install

```bash
git clone https://github.com/CodificationCodes/peerchat.git
cd peerchat
pip install .          # add --break-system-packages if pip complains about an "externally-managed-environment"
peerchat
```

## Using it

1. Enter a display name.
2. Arrow-key to **Host a Room**, **Join**, or **Scan Network**, press Enter.
3. **Host**: pick a port and share the address it shows you.
4. **Join**: enter `ip:port` for the same wifi, or a `wss://` address if
   the host is running behind a tunnel (needed on networks with client
   isolation).
5. **Scan**: finds rooms automatically on the same wifi, arrow down,
   Enter to join. Only works on the same local network.
6. Type a message, press Enter to send. `/quit` to leave.

## Running a dedicated server

For an always-on room, use `peerchat-server` no terminal UI, just the room, operated through
command-line flags:

```bash
peerchat-server --name "My Room" --port 5000
```

It prints the address to share and then runs until you stop it (Ctrl+C).
By default it logs joins/leaves and *that* someone sent a message, but not
the message text, add `--verbose` if you want full message content in the
log too. See `peerchat-server --help` for all options (`--bind`,
`--no-discovery`).

To reach it from outside your LAN, put it behind a tunnel, 
Cloudflare Tunnel works well and is what this project is
built/tested against: point your tunnel's public hostname at
`http://localhost:5000` (HTTP ingress transparently proxies the WebSocket
upgrade, no extra config needed), then friends connect from the app's
**Join** screen with `wss://yourhostname`.Enter

**Keeping it running permanently:** see `peerchat.service` in this repo for
a ready-to-edit systemd unit, it restarts the server automatically if it
crashes and starts it on boot. Copy it to `/etc/systemd/system/peerchat.service`
after editing the paths inside, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now peerchat
journalctl -u peerchat -f   # watch the logs
```


## Updating

Git-installed packages don't always upgrade cleanly through pipx, force a reinstall through:

```bash
pipx install --force git+https://github.com/CodificationCodes/peerchat.git
```

Or, if you installed manually:

```bash
cd peerchat && git pull && pip install .
```
