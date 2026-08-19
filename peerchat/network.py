"""Networking layer for Peer Chat — WebSocket edition.

Why WebSockets instead of raw TCP sockets:

Raw custom TCP protocols get silently dropped by school/corporate firewalls
that do deep packet inspection (DPI) — the firewall lets the TCP handshake
and first packet or two through, then blocks further traffic once it
realizes the protocol isn't HTTP/TLS. WebSockets running over a real TLS
connection on port 443 (wss://) look identical to normal HTTPS traffic to
any firewall or "client isolation" policy, so they get through.

This module keeps the exact same public API as the old raw-socket version
(ChatServer, ClientConnection with connect()/send_message()/send_typing()/
quit(), and a thread-safe incoming_queue) so `ui.py` requires zero changes.
Internally, each class runs its own asyncio event loop on a background
thread and bridges results back to the caller's thread via a thread-safe
queue.Queue and asyncio.run_coroutine_threadsafe().

Two ways to run a room:
- Plain LAN, no restrictions: friends connect with ws://<ip>:<port> — same
  as before, just point Join at the IP:port.
- Across a locked-down network (school wifi, client isolation, DPI
  firewalls): run the server on your own machine/home server, expose it
  through a Cloudflare Tunnel (or similar) as a public hostname, and friends
  connect with wss://<yourdomain>. Cloudflare Tunnel's HTTP ingress natively
  proxies WebSocket upgrades, so no extra tunnel configuration is needed
  beyond pointing a public hostname at ws://localhost:<port>.
"""

import asyncio
import datetime
import re
import socket
import threading
import time
from typing import Optional

import websockets
from websockets.exceptions import ConnectionClosed

DISCOVERY_PORT = 50000
DISCOVERY_MSG = b"DISCOVER_ROOMS"
DISCOVERY_RESP_PREFIX = "ROOM_INFO::"

IDLE_SECONDS = 90  # no activity for this long -> marked away
IDLE_CHECK_INTERVAL = 5  # how often the server checks for idle clients


def now_timestamp() -> str:
    return datetime.datetime.now().strftime("%H:%M")


def get_local_ip() -> str:
    """Return the likely LAN IP for this host."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def valid_ip(ip: str) -> bool:
    pattern = r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$"
    if not re.match(pattern, ip):
        return False
    parts = ip.split('.')
    return all(0 <= int(p) <= 255 for p in parts)


def valid_port(port_str: str) -> bool:
    try:
        p = int(port_str)
        return 1 <= p <= 65535
    except Exception:
        return False


def build_ws_uri(addr: str, default_port: int = 5000) -> Optional[str]:
    """Turn user input into a ws:// or wss:// URI.

    Accepts:
    - a full URI already: "ws://host:port" or "wss://host" -> used as-is
    - "ip:port" or "host:port" -> ws://host:port (assumed local/plain)
    - a bare hostname with no port -> ws://host:<default_port>
    Returns None if it can't make sense of the input.
    """
    addr = addr.strip()
    if not addr:
        return None
    if addr.startswith("ws://") or addr.startswith("wss://"):
        return addr
    if ':' in addr:
        host, port_str = addr.rsplit(':', 1)
        if not host or not valid_port(port_str):
            return None
        return f"ws://{host}:{port_str}"
    # bare hostname, no port given
    return f"ws://{addr}:{default_port}"


class ChatServer:
    """WebSocket chat server that accepts clients and relays messages.

    Message protocol (each WebSocket text frame is one frame, no manual
    line-buffering needed like the old raw-socket version):
    - Client sends: JOIN::<name> right after connecting
    - Client sends: MSG::<text> for chat messages
    - Client sends: TYPING::1 / TYPING::0 when starting/stopping typing
    - Client sends: QUIT to leave
    """

    def __init__(self, host_ip: str, port: int, host_name: str):
        self.host_ip = host_ip
        self.port = port
        self.host_name = host_name
        self._clients = {}  # websocket -> name
        self._last_activity = {}  # websocket -> timestamp
        self._idle = {}  # websocket -> bool
        self.running = False

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._start_error: Optional[Exception] = None

    # ---- lifecycle -------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        if self._start_error:
            raise self._start_error
        self.running = True

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        except Exception as e:
            self._start_error = e
            self._ready.set()

    async def _serve(self) -> None:
        try:
            self._server = await websockets.serve(self._handler, "0.0.0.0", self.port)
        except Exception as e:
            self._start_error = e
            self._ready.set()
            return
        self._ready.set()
        asyncio.ensure_future(self._idle_check_loop())
        await self._server.wait_closed()

    def stop(self) -> None:
        self.running = False
        if not self._loop:
            return
        fut = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        try:
            fut.result(timeout=5)
        except Exception:
            pass

    async def _shutdown(self) -> None:
        for ws in list(self._clients.keys()):
            try:
                await ws.send(f"[{now_timestamp()}] * Host is closing the room. *")
            except Exception:
                pass
            try:
                await ws.close()
            except Exception:
                pass
        self._clients.clear()
        if self._server:
            self._server.close()

    # ---- per-client handling ---------------------------------------

    async def _handler(self, ws) -> None:
        name = "Unknown"
        try:
            first = await ws.recv()
            if isinstance(first, str) and first.startswith("JOIN::"):
                name = first.split("JOIN::", 1)[1].strip() or "Unknown"
            self._clients[ws] = name
            self._last_activity[ws] = time.time()
            self._idle[ws] = False
            await self.broadcast_system(f"{name} has joined the room.")

            async for line in ws:
                if not isinstance(line, str):
                    continue
                if line == "QUIT":
                    break
                if line.startswith("MSG::"):
                    text = line.split("MSG::", 1)[1]
                    await self._mark_active(ws, name)
                    formatted = f"[{now_timestamp()}] {name}: {text}"
                    await self.broadcast(formatted)
                elif line.startswith("TYPING::"):
                    state = line.split("TYPING::", 1)[1].strip()
                    await self._mark_active(ws, name)
                    await self.broadcast_except(ws, f"TYPING_STATUS::{name}::{state}")
        except ConnectionClosed:
            pass
        except Exception:
            pass
        finally:
            left_name = self._clients.pop(ws, None)
            self._last_activity.pop(ws, None)
            self._idle.pop(ws, None)
            try:
                await ws.close()
            except Exception:
                pass
            if left_name is not None:
                await self.broadcast(f"TYPING_STATUS::{left_name}::0")
                await self.broadcast_system(f"{left_name} has left the room.")

    async def _idle_check_loop(self) -> None:
        while self.running or self._clients:
            await asyncio.sleep(IDLE_CHECK_INTERVAL)
            now = time.time()
            newly_idle = []
            for ws, last in list(self._last_activity.items()):
                if ws not in self._clients:
                    continue
                if not self._idle.get(ws) and (now - last) > IDLE_SECONDS:
                    self._idle[ws] = True
                    newly_idle.append(self._clients[ws])
            for name in newly_idle:
                await self.broadcast(f"IDLE_STATUS::{name}::1")
                await self.broadcast_system(f"{name} is now away")

    async def _mark_active(self, ws, name: str) -> None:
        self._last_activity[ws] = time.time()
        if self._idle.get(ws):
            self._idle[ws] = False
            await self.broadcast(f"IDLE_STATUS::{name}::0")
            await self.broadcast_system(f"{name} is back")

    # ---- broadcasting -------------------------------------------------

    async def broadcast(self, message: str) -> None:
        dead = []
        for ws in list(self._clients.keys()):
            try:
                await ws.send(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.pop(ws, None)

    async def broadcast_except(self, exclude_ws, message: str) -> None:
        dead = []
        for ws in list(self._clients.keys()):
            if ws is exclude_ws:
                continue
            try:
                await ws.send(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.pop(ws, None)

    async def broadcast_system(self, text: str) -> None:
        await self.broadcast(f"[{now_timestamp()}] * {text} *")

    def get_participant_count(self) -> int:
        return max(1, len(self._clients))


class DiscoveryListener:
    """Responds to LAN discovery broadcasts with ROOM_INFO lines.

    Unrelated to the WebSocket change — this is plain UDP broadcast on the
    local network only, used for the "Scan Network" feature. Firewalls that
    block cross-client traffic will still block this; it's a LAN-only
    convenience feature, not a way through isolation.
    """

    def __init__(self, server: ChatServer):
        self.server = server
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._sock.bind(("0.0.0.0", DISCOVERY_PORT))
        except Exception:
            self._sock = None
        self.running = False

    def start(self) -> None:
        if not self._sock:
            return
        self.running = True
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _listen_loop(self) -> None:
        while self.running:
            try:
                data, addr = self._sock.recvfrom(1024)
            except Exception:
                break
            if not data:
                continue
            if data == DISCOVERY_MSG:
                ip = get_local_ip()
                response = (DISCOVERY_RESP_PREFIX +
                            f"{self.server.host_name}::{ip}::{self.server.port}::{self.server.get_participant_count()}").encode('utf-8')
                try:
                    self._sock.sendto(response, addr)
                except Exception:
                    pass

    def stop(self) -> None:
        self.running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass


def discovery_scan(timeout: float = 2.0):
    """Broadcast a discovery packet and collect ROOM_INFO replies. LAN-only."""
    results = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(timeout)
    try:
        s.sendto(DISCOVERY_MSG, ("255.255.255.255", DISCOVERY_PORT))
        start = time.time()
        while True:
            try:
                data, _addr = s.recvfrom(1024)
            except socket.timeout:
                break
            try:
                text = data.decode('utf-8', errors='ignore')
            except Exception:
                continue
            if text.startswith(DISCOVERY_RESP_PREFIX):
                payload = text.split(DISCOVERY_RESP_PREFIX, 1)[1]
                parts = payload.split("::")
                if len(parts) >= 4:
                    name, ip, port, count = parts[:4]
                    try:
                        results.append({
                            "name": name,
                            "ip": ip,
                            "port": int(port),
                            "count": int(count),
                        })
                    except Exception:
                        pass
            if time.time() - start > timeout:
                break
    finally:
        s.close()
    return results


class ClientConnection:
    """Client-side WebSocket connection.

    Delivers incoming lines into a thread-safe queue.Queue (created by the
    caller) exactly like the old raw-socket version, so ui.py's polling
    _drain() loop needs no changes.

    `server_ip`/`server_port` are kept as constructor args for backward
    compatibility with existing call sites in ui.py — pass either a bare
    "ip"/"host" + port, or set server_ip to a full ws://.../wss://... URI
    and server_port will be ignored.
    """

    def __init__(self, server_ip: str, server_port: int, display_name: str, incoming_queue, on_disconnect=None):
        self.server_ip = server_ip
        self.server_port = server_port
        self.display_name = display_name
        self.incoming_queue = incoming_queue
        self.on_disconnect = on_disconnect
        self.running = False

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._connect_error: Optional[Exception] = None

    def _resolve_uri(self) -> str:
        if self.server_ip.startswith("ws://") or self.server_ip.startswith("wss://"):
            return self.server_ip
        return f"ws://{self.server_ip}:{self.server_port}"

    def connect(self) -> None:
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=10)
        if self._connect_error:
            raise self._connect_error
        self.running = True

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._connect_and_listen())
        except Exception as e:
            if not self._ready.is_set():
                self._connect_error = e
                self._ready.set()

    async def _connect_and_listen(self) -> None:
        uri = self._resolve_uri()
        try:
            self._ws = await websockets.connect(uri, open_timeout=8)
        except Exception as e:
            self._connect_error = e
            self._ready.set()
            return
        try:
            await self._ws.send(f"JOIN::{self.display_name}")
        except Exception as e:
            self._connect_error = e
            self._ready.set()
            return
        self._ready.set()
        try:
            async for message in self._ws:
                if isinstance(message, str):
                    try:
                        self.incoming_queue.put(message)
                    except Exception:
                        pass
        except ConnectionClosed:
            pass
        except Exception:
            pass
        finally:
            self.running = False
            if self.on_disconnect:
                try:
                    self.on_disconnect()
                except Exception:
                    pass

    def _send_threadsafe(self, text: str) -> bool:
        if not self._loop or not self._ws:
            return False
        try:
            asyncio.run_coroutine_threadsafe(self._ws.send(text), self._loop)
            return True
        except Exception:
            return False

    def send_message(self, text: str) -> bool:
        return self._send_threadsafe(f"MSG::{text}")

    def send_typing(self, is_typing: bool) -> bool:
        return self._send_threadsafe(f"TYPING::{1 if is_typing else 0}")

    def quit(self) -> None:
        self.running = False
        if not self._loop or not self._ws:
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self._quit_async(), self._loop)
            fut.result(timeout=3)
        except Exception:
            pass

    async def _quit_async(self) -> None:
        try:
            await self._ws.send("QUIT")
        except Exception:
            pass
        try:
            await self._ws.close()
        except Exception:
            pass


__all__ = [
    'ChatServer', 'DiscoveryListener', 'discovery_scan', 'ClientConnection',
    'get_local_ip', 'valid_ip', 'valid_port', 'build_ws_uri',
]
