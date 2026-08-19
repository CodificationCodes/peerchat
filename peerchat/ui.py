"""Textual UI for Peer Chat.

Contains the App and Screen classes. Imports `network.py` for all networking
operations and uses a thread-safe queue to receive incoming messages from
background socket threads.
"""

import queue
import threading
import time
from typing import Optional

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import (
    Header, Footer, Input, Button, Static, ListView, ListItem, Label, RichLog,
)

from . import network


class NameScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Peer Chat", id="title")
        yield Label("What should people see as your name?", id="subtitle")
        yield Input(placeholder="Display name", id="name")
        yield Button("Continue", id="continue", variant="success")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one('#name', Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'continue':
            self._submit()

    def _submit(self) -> None:
        name = self.query_one('#name', Input).value.strip()
        if not name:
            self.app.push_screen(MessageScreen("Please enter a name"))
            return
        self.app.display_name = name
        self.app.switch_screen(MenuScreen())


class MenuScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(f"Peer Chat — {self.app.display_name}", id="title")
        yield ListView(
            ListItem(Label("Host a Room"), id="menu-host"),
            ListItem(Label("Join by IP"), id="menu-join"),
            ListItem(Label("Scan Network"), id="menu-scan"),
            ListItem(Label("Change name"), id="menu-name"),
            ListItem(Label("Quit"), id="menu-quit"),
        )
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id
        if item_id == "menu-host":
            self.app.push_screen(HostScreen())
        elif item_id == "menu-join":
            self.app.push_screen(JoinScreen())
        elif item_id == "menu-scan":
            self.app.push_screen(ScanScreen())
        elif item_id == "menu-name":
            self.app.switch_screen(NameScreen())
        else:
            self.app.exit()


class HostScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Host a Room", id="subtitle")
        yield Input(placeholder="Port (default 5000)", id="port")
        yield Button("Start Hosting", id="start", variant="success")
        yield Button("Back", id="back")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'start':
            name = self.app.display_name or 'Host'
            port_text = self.query_one('#port', Input).value.strip() or '5000'
            if not network.valid_port(port_text):
                self.app.push_screen(MessageScreen("Invalid port"))
                return
            port = int(port_text)
            self.app.start_host(name, port)
        else:
            self.app.pop_screen()


class JoinScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Join a Room", id="subtitle")
        yield Label(
            "LAN: ip:port  •  Remote (e.g. school wifi): wss://yourdomain",
            id="join-hint",
        )
        yield Input(placeholder="ip:port  or  wss://chat.example.com", id="addr")
        yield Button("Connect", id="connect", variant="success")
        yield Button("Back", id="back")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'connect':
            name = self.app.display_name or 'Guest'
            addr = self.query_one('#addr', Input).value.strip()
            uri = network.build_ws_uri(addr)
            if not uri:
                self.app.push_screen(MessageScreen("Invalid address. Use ip:port or ws(s)://host"))
                return
            self.app.join_room(uri, name)
        else:
            self.app.pop_screen()


class ScanScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Scanning for Rooms...", id="subtitle")
        yield ListView(id="results")
        yield Button("Back", id="back")
        yield Footer()

    def on_mount(self) -> None:
        self.keep_scanning = True
        threading.Thread(target=self._scan_loop, daemon=True).start()

    def _scan_loop(self) -> None:
        while getattr(self, 'keep_scanning', False):
            rooms = network.discovery_scan(timeout=1.5)

            def update(rooms=rooms):
                listview = self.query_one('#results', ListView)
                listview.clear()
                if not rooms:
                    listview.append(ListItem(Label("No active rooms — /r to rescan"), id="no-rooms"))
                else:
                    for i, r in enumerate(rooms):
                        text = f"{r['name']}  -  {r['ip']}:{r['port']}  -  {r['count']} people"
                        item = ListItem(Label(text), id=f"room-{i}")
                        item.room_addr = (r['ip'], r['port'])
                        listview.append(item)

            try:
                self.app.call_from_thread(update)
            except Exception:
                pass
            time.sleep(2.0)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'back':
            self.keep_scanning = False
            self.app.pop_screen()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        addr = getattr(item, 'room_addr', None)
        if not addr:
            return
        self.keep_scanning = False
        ip, port = addr
        self.app.join_room(f"ws://{ip}:{port}", self.app.display_name or 'Guest')


class MessageScreen(Screen):
    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self.message, id="message")
        yield Button("OK", id="ok")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'ok':
            self.app.pop_screen()


class ChatScreen(Screen):
    TYPING_TIMEOUT = 2.5  # seconds of no typing before we tell the server we've stopped

    def __init__(self, title: str, client_conn: network.ClientConnection,
                 server_obj: Optional[network.ChatServer] = None,
                 disc: Optional[network.DiscoveryListener] = None):
        super().__init__()
        self.title_text = title
        self.client_conn = client_conn
        self.server_obj = server_obj
        self.disc = disc
        self.incoming = client_conn.incoming_queue
        self.typing_users = set()
        self._am_typing = False
        self._typing_timer = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label(self.title_text, id='room')
        yield RichLog(id="log", wrap=True, markup=True)
        yield Label("", id="typing-indicator")
        yield Input(placeholder='Type message and press Enter (/quit to leave)', id='input')
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.2, self._drain)
        self.query_one('#input', Input).focus()

    def _drain(self) -> None:
        log = self.query_one('#log', RichLog)
        changed_typing = False
        for _ in range(200):  # cap per tick so a burst can't block the UI loop
            try:
                msg = self.incoming.get_nowait()
            except queue.Empty:
                break
            if msg.startswith("TYPING_STATUS::"):
                _, name, state = msg.split("::", 2)
                if state == "1":
                    self.typing_users.add(name)
                else:
                    self.typing_users.discard(name)
                changed_typing = True
                continue
            if msg.startswith("IDLE_STATUS::"):
                # purely informational for now; the human-readable "X is away"
                # / "X is back" system line arrives separately via broadcast_system
                continue
            if '] * ' in msg:
                log.write(f"[dim italic]{msg}[/]")
                if " has left the room" in msg:
                    # best-effort: stop showing a typing indicator for someone who left
                    for name in list(self.typing_users):
                        if msg.split('*', 1)[1].strip().startswith(name):
                            self.typing_users.discard(name)
                            changed_typing = True
            else:
                log.write(msg)
        if changed_typing:
            self._update_typing_label()

    def _update_typing_label(self) -> None:
        label = self.query_one('#typing-indicator', Label)
        names = sorted(self.typing_users)
        if not names:
            label.update("")
        elif len(names) == 1:
            label.update(f"{names[0]} is typing...")
        elif len(names) == 2:
            label.update(f"{names[0]} and {names[1]} are typing...")
        else:
            label.update(f"{len(names)} people are typing...")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != 'input':
            return
        has_text = bool(event.value.strip())
        if has_text and not self._am_typing:
            self._am_typing = True
            self.client_conn.send_typing(True)
        elif not has_text and self._am_typing:
            self._am_typing = False
            self.client_conn.send_typing(False)
        if self._typing_timer is not None:
            self._typing_timer.stop()
            self._typing_timer = None
        if has_text:
            self._typing_timer = self.set_timer(self.TYPING_TIMEOUT, self._typing_timeout)

    def _typing_timeout(self) -> None:
        if self._am_typing:
            self._am_typing = False
            self.client_conn.send_typing(False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.query_one('#input', Input).value = ''
        if self._typing_timer is not None:
            self._typing_timer.stop()
            self._typing_timer = None
        if self._am_typing:
            self._am_typing = False
            self.client_conn.send_typing(False)
        if not text:
            return
        if text == '/quit':
            try:
                self.client_conn.quit()
            except Exception:
                pass
            if self.server_obj:
                try:
                    if self.disc:
                        self.disc.stop()
                except Exception:
                    pass
                try:
                    self.server_obj.stop()
                except Exception:
                    pass
            self.app.pop_screen()
            return
        ok = self.client_conn.send_message(text)
        if not ok:
            self.query_one('#log', RichLog).write('[red]Failed to send (disconnected)[/]')


class PeerChatApp(App):
    CSS = """
    #title { text-align: center; text-style: bold; padding: 1; }
    #subtitle { text-align: center; padding: 1; }
    #room { text-align: center; text-style: bold; background: $primary; padding: 1; }
    #typing-indicator { color: $text-muted; text-style: italic; padding: 0 2; height: 1; }
    #join-hint { color: $text-muted; text-style: italic; text-align: center; padding: 0 2; }
    Input { margin: 1 2; }
    Button { margin: 0 2; }
    """

    display_name: Optional[str] = None

    def on_mount(self) -> None:
        self.push_screen(NameScreen())

    def start_host(self, display_name: str, port: int) -> None:
        self.display_name = display_name
        local_ip = network.get_local_ip()
        server = network.ChatServer(local_ip, port, display_name)
        try:
            server.start()
        except Exception as e:
            self.push_screen(MessageScreen(f"Failed to start server: {e}"))
            return
        disc = network.DiscoveryListener(server)
        disc.start()
        incoming = queue.Queue()
        client = network.ClientConnection(f'ws://127.0.0.1:{port}', 0, display_name, incoming)
        try:
            client.connect()
        except Exception as e:
            server.stop()
            self.push_screen(MessageScreen(f"Failed to start host client: {e}"))
            return
        title = f"Room by {display_name} @ {local_ip}:{port}"
        self.push_screen(ChatScreen(title, client, server, disc))

    def join_room(self, address: str, display_name: str) -> None:
        """address is a full ws:// or wss:// URI, e.g. from build_ws_uri()."""
        self.display_name = display_name
        incoming = queue.Queue()
        client = network.ClientConnection(address, 0, display_name, incoming, on_disconnect=self._on_disconnect)
        try:
            client.connect()
        except Exception as e:
            self.push_screen(MessageScreen(f"Failed to connect: {e}"))
            return
        title = f"Connected to {address} as {display_name}"
        self.push_screen(ChatScreen(title, client))

    def _on_disconnect(self) -> None:
        def notify():
            self.push_screen(MessageScreen("Disconnected from server"))
        try:
            self.call_from_thread(notify)
        except Exception:
            pass


def run_app() -> None:
    app = PeerChatApp()
    app.run()


if __name__ == '__main__':
    run_app()