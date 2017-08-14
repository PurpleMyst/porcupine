#onnect
import collections
import enum
import queue
import socket
import threading


class IrcEvent(enum.Enum):
    # The comments above each enum value represent the parameters they should
    # come with.

    # ()
    connected = enum.auto()

    # (channel,)
    self_joined = enum.auto()

    # (channel, reason)
    self_parted = enum.auto()

    # (sender, channel)
    user_joined = enum.auto()

    # (sender, channel, reason)
    user_parted = enum.auto()

    # (recipient, text)
    sent_privmsg = enum.auto()

    # (sender, recipient, text)
    recieved_privmsg = enum.auto()


class _IrcInternalEvent(enum.Enum):
    got_message = enum.auto()

    should_join = enum.auto()
    should_part = enum.auto()
    should_send_privmsg = enum.auto()


User = collections.namedtuple("User", ["nick", "user", "host"])
Server = collections.namedtuple("Server", ["name"])
_Message = collections.namedtuple("_Message", ["sender", "command", "args"])


class IrcCore:
    def __init__(self, host, port, nick):
        self._host = host
        self._port = port
        self._running = True
        self.nick = nick

        self._sock = socket.socket()

        self._linebuffer = collections.deque()

        self._internal_queue = queue.Queue()
        self.event_queue = queue.Queue()

    def __del__(self):
        # We shouldn't really use __del__, but just in case we get the
        # chance...
        self._running = False
        self._send("QUIT :Goodbye!")

    def _send(self, *parts):
        data = " ".join(parts).encode("utf-8") + b"\r\n"
        self._sock.sendall(data)

    def _recv_line(self):
        if not self._linebuffer:
            data = bytearray()
            while not data.endswith(b"\r\n"):
                chunk = self._sock.recv(4096)
                if chunk:
                    data += chunk
                else:
                    raise RuntimeError("Server closed the connection!")
            lines = data.decode("utf-8", errors='replace').split("\r\n")
            self._linebuffer.extend(lines)
        return self._linebuffer.popleft()

    def _add_messages_to_internal_queue(self):
        # We need to have this function because it would be very complicated to
        # wait on two different queues, one for requests to send stuff and one
        # recieved messages.
        while self._running:
            line = self._recv_line()
            if line.startswith("PING"):
                self._send(line.replace("PING", "PONG", 1))
                continue
            self._internal_queue.put((_IrcInternalEvent.got_message,
                                      self._split_line(line)))

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
        return _Message(sender, command, args)

    def _mainloop(self):
        while self._running:
            event, *args = self._internal_queue.get()

            if event == _IrcInternalEvent.got_message:
                [msg] = args
                if msg.command == "PRIVMSG":
                    recipient, text = msg.args
                    self.event_queue.put((IrcEvent.recieved_privmsg,
                                          msg.sender, recipient, text))
                elif msg.command == "JOIN":
                    [channel] = msg.args
                    self.event_queue.put((IrcEvent.user_joined,
                                          msg.sender, channel))
                elif msg.command == "PART":
                    channel = msg.args[0]
                    reason = msg.args[1] if len(msg.args) >= 2 else None
                    self.event_queue.put((IrcEvent.user_parted,
                                          msg.sender, channel, reason))
            elif event == _IrcInternalEvent.should_join:
                [channel] = args
                self._send("JOIN", channel)
                self.event_queue.put((IrcEvent.self_joined, channel))
            elif event == _IrcInternalEvent.should_part:
                channel, reason = args
                if reason is None:
                    self._send("PART", channel)
                else:
                    self._send("PART", channel, ":" + reason)
                self.event_queue.put((IrcEvent.self_parted, channel, reason))
            elif event == _IrcInternalEvent.should_send_privmsg:
                recipient, text = args
                self._send("PRIVMSG", recipient, ":" + text)
                self.event_queue.put((IrcEvent.sent_privmsg, recipient, text))
            else:
                raise RuntimeError("Unrecognized internal event!")

            self._internal_queue.task_done()

    def connect(self):
        # We separate this into its own sub-worker instead of using the queues
        # for _mainloop because this *must* happen before mainloop.
        def worker():
            self._sock.connect((self._host, self._port))
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

            self.event_queue.put((IrcEvent.connected,))
            threading.Thread(target=self._add_messages_to_internal_queue).start()
            threading.Thread(target=self._mainloop).start()

        threading.Thread(target=worker).start()

    def join_channel(self, channel):
        self._internal_queue.put((_IrcInternalEvent.should_join, channel))

    def part_channel(self, channel, reason=None):
        self._internal_queue.put((_IrcInternalEvent.should_part,
                                  channel, reason))

    def send_privmsg(self, recipient, text):
        self._internal_queue.put((_IrcInternalEvent.should_send_privmsg,
                                  recipient, text))

    def quit(self):
        self._running = False
