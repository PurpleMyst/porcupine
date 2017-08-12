#!/usr/bin/env python3
import enum
import queue


class IrcEvent(enum.Enum):
    join = enum.auto()
    part = enum.auto()
    privmsg = enum.auto()


class IrcCore:
    def __init__(self, host, port):
        self._host = host
        self._port = port

        self.event_queue = queue.Queue()

    def connect(self):
        pass

    def join_channel(self, channel):
        pass

    def part_channel(self, channel, reason=None):
        pass

    def send_privmsg(self, recipient, text):
        pass
