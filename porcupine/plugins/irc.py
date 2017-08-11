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


class ActualIrc:
    def __init__(self, encoding="utf-8"):
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

        fr = self._init_frame = tk.Frame(self)

        self._server_entry = self._add_entry(fr, 0, "Server:")
        self._nick_entry = self._add_entry(fr, 1, "Nickname:")
        self._chan_entry = self._add_entry(fr, 2, "Channel:")

        self._start_button = tk.Button(fr, text="Start", command=self._start)
        self._start_button.grid(row=3, column=0)

        self._status_label = tk.Label(fr)
        self._status_label.grid(row=3, column=1, columnspan=2, sticky='nswe')

        self._init_frame.pack()

    def _add_entry(self, frame, row, text, callback=None):
        tk.Label(frame, text=text).grid(row=row, column=0)
        entry = tk.Entry(frame, width=35, font='TkFixedFont')
        entry.bind('<Escape>', lambda event: self.pack_forget())
        if callback is not None:
            entry.bind('<Return>', lambda event: callback())
        entry.grid(row=row, column=1, sticky='we')
        return entry

    def _start(self):
        server = self._server_entry.get()
        nick = self._nick_entry.get()
        chan = self._chan_entry.get()

        try:
            assert server
            assert nick
            assert chan
            assert " " not in nick
            assert chan.startswith("#")
        except AssertionError:
            self._status_label["text"] = "Something is invalid!"
            return

        self._init_frame.pack_forget()

        threading.Thread(target=self._actual_irc,
                         args=(server, nick, chan)).start()

    def _actual_irc(self, server, nick, chan):
        irc_client = ActualIrc()
        irc_client.connect(nick, server)
        irc_client.join_channel(chan)

        threading.Thread(target=irc_client.mainloop).start()
        while True:
            msg = irc_client.message_queue.get()
            # TODO: Actually show messages.
            irc_client.message_queue.task_done()


def go_onto_irc():
    manager = porcupine.get_tab_manager()
    manager.add_tab(IrcTab(manager))


def setup():
    porcupine.add_action(go_onto_irc,
                         "Games/IRC")
