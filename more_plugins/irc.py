#!/usr/bin/env python3
import collections
import queue
import socket
import threading
import tkinter as tk

import porcupine
from porcupine.tabs import Tab

User = collections.namedtuple("User", ["nick", "user", "host"])
Server = collections.namedtuple("Server", ["name"])
Message = collections.namedtuple("Message", ["sender", "command", "args"])


class IrcCore:
    def __init__(self, encoding="utf-8"):
        # TODO at some point: Private messages, multiple channels, multiple
        # servers maybe, colors, and an ever-present nicklist.
        self.nick = None
        self._server = None
        self.encoding = encoding

        self._linebuffer = collections.deque()
        self._sock = socket.socket()

        self.message_queue = queue.Queue()

    def _send(self, *parts):
        data = " ".join(parts).encode(self.encoding) + b"\r\n"
        self._sock.sendall(data)

    def _recv_line(self):
        if not self._linebuffer:
            data = bytearray()
            while not data.endswith(b"\r\n"):
                chunk = self._sock.recv(4096)
                if chunk:
                    data += chunk
                else:
                    raise IOError("Server closed the connection!")

            lines = data.decode(self.encoding, errors='replace').split("\r\n")
            self._linebuffer.extend(lines)
        return self._linebuffer.popleft()

    @staticmethod
    def _split_line(line):
        if line.startswith(":"):
            sender, command, *args = line.split(" ")
            sender = sender[1:]
            if "!" in sender:
                nick, sender = sender.split("!", 1)
                user, host = sender.split("@", 1)
                sender = User(nick, user, host)
            else:
                sender = Server(sender)
        else:
            sender = None
            command, *args = line.split(" ")
        for n, arg in enumerate(args):
            if arg.startswith(":"):
                temp = args[:n]
                temp.append(" ".join(args[n:])[1:])
                args = temp
                break
        return Message(sender, command, args)

    def connect(self, nick, host, port=6667):
        self.nick = nick
        self._server = (host, port)

        self._sock.connect(self._server)
        self._send("NICK", self.nick)
        self._send("USER", self.nick, "0", "*", ":" + self.nick)

        while True:
            line = self._recv_line()
            if line.startswith("PING"):
                self._send(line.replace("PING", "PONG", 1))
                continue
            msg = self._split_line(line)
            if msg.command == "001":
                break

    def join_channel(self, channel):
        self._send("JOIN", channel)

    def send_privmsg(self, recipient, text):
        self._send("PRIVMSG", recipient, ":" + text)

    def send_action(self, recipient, action):
        self._send("PRIVMSG", recipient,
                   ":\x01ACTION {}\x01".format(action))

    def quit(self, message="goodbye, world"):
        self._send("QUIT", ":" + message)

    def mainloop(self):
        while True:
            line = self._recv_line()
            if not line:
                continue
            if line.startswith("PING"):
                self._send(line.replace("PING", "PONG", 1))
                continue
            msg = self._split_line(line)
            self.message_queue.put(msg)


class IrcTab(Tab):
    def __init__(self, manager):
        super().__init__(manager)
        self.top_label['text'] = "IRC"
        self._init_frame = self._build_init_frame()

        # Because pylint is magic.
        self.irc_core = self.server = self.nick = self.chan = None

    def _build_init_frame(self):
        fr = tk.Frame(self)

        self._server_entry = self._add_entry(fr, 0, "Server:")
        self._nick_entry = self._add_entry(fr, 1, "Nickname:")
        self._chan_entry = self._add_entry(fr, 2, "Channel:")

        self._start_button = tk.Button(fr, text="Start", command=self._start)
        self._start_button.grid(row=3, column=0)

        self._status_label = tk.Label(fr)
        self._status_label.grid(row=3, column=1, columnspan=2, sticky='nswe')

        fr.pack()
        return fr

    def _add_entry(self, frame, row, text, callback=None):
        tk.Label(frame, text=text).grid(row=row, column=0)
        entry = tk.Entry(frame, width=35, font='TkFixedFont')
        entry.bind('<Escape>', lambda event: self.pack_forget())
        entry.bind('<Control-A>', self._on_control_a)
        entry.bind('<Control-a>', self._on_control_a)
        if callback is not None:
            entry.bind('<Return>', lambda event: callback())
        entry.grid(row=row, column=1, sticky='we')
        return entry

    def _start(self):
        server = self._server_entry.get()
        nick = self._nick_entry.get()
        chan = self._chan_entry.get()

        if not (server and nick and chan and
                " " not in nick and
                chan.startswith("#")):
            self._status_label["text"] = "Something is invalid!"
            return

        self._init_frame.pack_forget()

        self.server = server
        self.nick = nick
        self.chan = chan
        self._connect_to_irc()

    def _connect_to_irc(self):
        textarea = tk.Frame(self)
        self._text = tk.Text(textarea, state='disabled')
        self._text.pack(side='left', fill='both', expand=True)
        scrollbar = tk.Scrollbar(textarea, command=self._text.yview)
        scrollbar.pack(side='right', fill='y')
        self._text['yscrollcommand'] = scrollbar.set
        textarea.pack(fill='both', expand=True)

        entry = tk.Entry(self, font='TkFixedFont')
        entry.pack(fill='x')
        entry.bind('<Return>', self._on_enter)
        entry.bind('<Control-A>', self._on_control_a)
        entry.bind('<Control-a>', self._on_control_a)

        self._show_info("Connecting...")
        self.irc_core = IrcCore()
        self.irc_core.connect(self.nick, self.server)
        saelf.irc_core.join_channel(self.chan)

        self.bind("<Destroy>", lambda _: self.irc_core.quit())

        threading.Thread(target=self.irc_core.mainloop).start()
        self._handle_messages()

    def _handle_messages(self):
        try:
            msg = self.irc_core.message_queue.get(block=False)
        except queue.Empty:
            self.after(100, self._handle_messages)
            return

        if msg.command == "353":
            self._show_info("People present: %s" % (msg.args[3],))
        elif msg.command == "366":
            # We wait until the end of the nick list to say we're
            # connected, even though we may actually be connected earlier.
            self._show_info("Connected!")
        elif msg.command == "JOIN":
            self._show_info("%s joined." % (msg.sender.nick,))
        elif msg.command == "PART":
            reason = msg.args[1] if len(msg.args) >= 2 else "No reason."
            self._show_info("%s parted. (%s)" % (msg.sender.nick, reason))
        elif msg.command == "PRIVMSG" and msg.args[0] == self.chan:
            self._show_message(msg.sender.nick, msg.args[1])
        self.irc_core.message_queue.task_done()

        self.after(100, self._handle_messages)

    def _show_message(self, sender_nick, text):
        self._text['state'] = 'normal'
        self._text.insert('end', "<%s> %s" % (sender_nick, text))
        self._text.insert('end', '\n')
        self._text.see('end')
        self._text['state'] = 'disabled'

    def _show_info(self, info):
        self._text['state'] = 'normal'
        self._text.insert('end', "[INFO] %s" % (info,))
        self._text.insert('end', '\n')
        self._text.see('end')
        self._text['state'] = 'disabled'

    @staticmethod
    def _on_control_a(event):
        entry = event.widget
        entry.selection_range(0, 'end')
        return 'break'

    def _on_enter(self, event):
        entry = event.widget
        msg = entry.get()
        if getattr(self, "irc_core", None) is not None:
            self.irc_core.send_privmsg(self.chan, msg)
            self._show_message(self.nick, msg)
        else:
            self._show_info("You're not connected yet!")
        entry.delete(0, 'end')


def go_onto_irc():
    manager = porcupine.get_tab_manager()
    manager.add_tab(IrcTab(manager))


def setup():
    porcupine.add_action(go_onto_irc,
                         "Games/IRC")
