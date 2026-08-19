# Peer Chat

A terminal chat app. No account, no central server required — anyone can
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

That's it — the installer sets up an isolated environment automatically
(using `pipx` if you have it, or a dedicated virtual environment if not),
so it won't interfere with anything else on your system.

### Windows (Command Prompt / PowerShell)

```powershell
git clone https://github.com/CodificationCodes/peerchat.git
cd peerchat
py -m pip install --user .
py -m peerchat.cli
```

`py -m peerchat.cli` works even if your Python Scripts folder is not on PATH.
If you want to run just `peerchat`, add your user Scripts folder to PATH.

### Manual install

If you'd rather not pipe a script into bash (fair enough), do it by hand:

```bash
git clone https://github.com/CodificationCodes/peerchat.git
cd peerchat
pip install .          # add --break-system-packages if pip complains about
                        # an "externally-managed-environment"
peerchat
```

## Using it

1. Enter a display name.
2. Arrow-key to **Host a Room**, **Join**, or **Scan Network**, press Enter.
3. **Host**: pick a port and share the address it shows you.
4. **Join**: enter `ip:port` for the same wifi, or a `wss://` address if
   the host is running behind a tunnel (needed on networks with client
   isolation, e.g. most school wifi — ask whoever's hosting).
5. **Scan**: finds rooms automatically on the same wifi — arrow down,
   Enter to join. Only works on the same local network.
6. Type a message, press Enter to send. `/quit` to leave.

While chatting you'll see live typing indicators and away/back status for
everyone in the room.

## Updating

```bash
pipx upgrade peerchat
```

or, if you installed manually:

```bash
cd peerchat && git pull && pip install .
```
