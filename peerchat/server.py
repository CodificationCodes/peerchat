"""Headless dedicated server for Peer Chat.

Runs a single always-on room with no terminal UI — meant to run under
systemd (or similar) on a machine you keep online, typically reached
through a Cloudflare Tunnel as wss://yourdomain rather than a raw IP.

Usage:
    peerchat-server --name "Spike's Room" --port 5000
    peerchat-server --name "Spike's Room" --port 5000 --verbose   # also log message text
    peerchat-server --name "Spike's Room" --port 5000 --no-discovery
"""

import argparse
import signal
import sys
import time

from . import network


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="peerchat-server",
        description="Run a Peer Chat room as a standalone, always-on server.",
    )
    p.add_argument(
        "--name", "-n", default="Room",
        help="Room / host display name shown to people who join (default: 'Room')",
    )
    p.add_argument(
        "--port", "-p", type=int, default=5000,
        help="Port to listen on (default: 5000)",
    )
    p.add_argument(
        "--bind", default="0.0.0.0",
        help="Address to bind to (default: 0.0.0.0, i.e. all interfaces)",
    )
    p.add_argument(
        "--no-discovery", action="store_true",
        help="Disable LAN UDP broadcast discovery (Scan Network won't find this room)",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Also print message text to the terminal (default: only join/leave/system events)",
    )
    return p.parse_args(argv)


def _print_banner(args: argparse.Namespace) -> None:
    local_ip = network.get_local_ip()
    print("=" * 60)
    print(f"  Peer Chat server — \"{args.name}\"")
    print("=" * 60)
    print(f"  Local network:  ws://{local_ip}:{args.port}")
    print(f"  Same machine:   ws://127.0.0.1:{args.port}")
    print()
    print("  For friends outside your LAN (e.g. school wifi), expose this")
    print(f"  port through a tunnel and share the resulting wss:// address")
    print(f"  instead — point your tunnel's ingress at ws://localhost:{args.port}.")
    print()
    if args.no_discovery:
        print("  LAN discovery (Scan Network): disabled")
    else:
        print("  LAN discovery (Scan Network): enabled")
    print("  Press Ctrl+C to stop the server.")
    print("=" * 60)
    print()


def _log_line(text: str, verbose: bool) -> None:
    """Print server activity to the terminal.

    By default, message *content* is not logged, only join/leave/system
    events and typing/idle transitions collapsed to activity — so running
    this on a machine you own doesn't put your friends' conversations in
    your terminal scrollback unless you explicitly ask for it.
    """
    ts = time.strftime("%H:%M:%S")
    if text.startswith("TYPING_STATUS::") or text.startswith("IDLE_STATUS::"):
        return  # internal protocol frames, never worth printing raw
    if "] * " in text:
        # system event: joined / left / away / back
        print(f"[{ts}] {text.split('] * ', 1)[1].rstrip(' *')}")
        return
    if verbose:
        print(f"[{ts}] {text}")
    else:
        # still show *that* activity happened, without the content
        if "] " in text and ": " in text:
            sender = text.split('] ', 1)[1].split(':', 1)[0]
            print(f"[{ts}] {sender} sent a message")


def main(argv=None) -> None:
    args = _parse_args(argv)

    server = network.ChatServer(args.bind, args.port, args.name)
    original_broadcast = server.broadcast

    async def _logging_broadcast(message: str) -> None:
        _log_line(message, args.verbose)
        await original_broadcast(message)

    server.broadcast = _logging_broadcast

    try:
        server.start()
    except Exception as e:
        print(f"Failed to start server: {e}", file=sys.stderr)
        sys.exit(1)

    disc = None
    if not args.no_discovery:
        disc = network.DiscoveryListener(server)
        disc.start()

    _print_banner(args)

    stop_requested = {"flag": False}

    def _handle_signal(signum, frame):
        stop_requested["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        while not stop_requested["flag"]:
            time.sleep(0.3)
    finally:
        print("\nShutting down...")
        if disc:
            disc.stop()
        server.stop()
        print("Server stopped.")


if __name__ == '__main__':
    main()
