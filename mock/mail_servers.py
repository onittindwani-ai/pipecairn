"""A tiny stub SMTP and IMAP server for tests and the demo. Not a real mail server.

SMTP: EHLO, AUTH PLAIN, MAIL, RCPT, DATA, RSET, NOOP, QUIT. Accepted messages land in `MailStore.outbox`.
To test failures: `MailStore.refuse_rcpt` maps an address to the reply the server gives at RCPT TO: a code (550 answers "550 5.1.1 ... User unknown", 450 a temporary one)
or a whole reply line ("554 5.7.1 <a@b>: Relay access denied"),
`silent_after_data` makes the server take the message and then never answer, `silent_at_quit` makes it ignore QUIT (the client times out), and
`quit_reply` replaces its answer to QUIT (for example "421 4.4.2 closing connection", which is not the 221 a client expects).
IMAP: CAPABILITY, LOGIN, SELECT, UID SEARCH (ALL, UNSEEN), UID FETCH (RFC822 or BODY.PEEK[], also BODY.PEEK[]<0.N> for the first N bytes and RFC822.SIZE; none marks the message read), UID STORE (flags), NOOP, LOGOUT.
Messages in `MailStore.inbox` are what the IMAP client sees. It speaks only what Python's smtplib and imaplib send.
"""

from __future__ import annotations

import re
import socketserver
import threading
import time
from dataclasses import dataclass, field


@dataclass
class MailStore:
    outbox: list[dict] = field(default_factory=list)  # accepted by SMTP: {"from","to","data"}
    inbox: list[dict] = field(default_factory=list)  # visible to IMAP: {"uid","raw","seen"}
    lock: threading.Lock = field(default_factory=threading.Lock)
    users: dict[str, str] = field(default_factory=lambda: {"demo": "demo-password"})
    refuse_rcpt: dict[str, int | str] = field(default_factory=dict)  # address -> SMTP reply code, or a whole reply line, at RCPT TO (for tests)
    silent_after_data: bool = False  # take the message, then never answer (for tests)
    silent_at_quit: bool = False  # never answer QUIT (for tests)
    quit_reply: str = ""  # the full reply line to QUIT instead of "221 bye" (for tests)
    silence_seconds: float = 3.0  # how long a silent server waits before it hangs up

    def deliver(self, raw: bytes) -> int:
        with self.lock:
            uid = len(self.inbox) + 1
            self.inbox.append({"uid": uid, "raw": raw, "seen": False})
            return uid


class _SMTP(socketserver.StreamRequestHandler):
    store: MailStore

    def _w(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode())
        self.wfile.flush()

    def handle(self) -> None:
        self._w("220 stub-smtp ready")
        mail_from, rcpts = "", []
        while True:
            line = self.rfile.readline().decode(errors="replace").rstrip("\r\n")
            if not line:
                return
            cmd = line.split(" ", 1)[0].upper()
            if cmd in ("EHLO", "HELO"):
                self.wfile.write(b"250-stub-smtp\r\n250 AUTH PLAIN\r\n")
                self.wfile.flush()
            elif cmd == "AUTH":
                self._w("235 ok")
            elif cmd == "MAIL":
                mail_from, rcpts = line.split(":", 1)[1].strip().strip("<>").split(">")[0], []
                self._w("250 ok")
            elif cmd == "RCPT":
                addr = line.split(":", 1)[1].strip().strip("<>").split(">")[0]
                code = self.store.refuse_rcpt.get(addr)
                if code:
                    if isinstance(code, str):
                        self._w(code)
                    else:
                        self._w(f"{code} 5.1.1 <{addr}>: Recipient address rejected: User unknown" if code >= 500 else f"{code} 4.2.0 <{addr}>: Try again later")
                else:
                    rcpts.append(addr)
                    self._w("250 ok")
            elif cmd == "DATA":
                self._w("354 end with a dot")
                chunks = []
                while True:
                    row = self.rfile.readline()
                    if row in (b".\r\n", b".\n", b""):
                        break
                    chunks.append(row[1:] if row.startswith(b"..") else row)
                with self.store.lock:
                    self.store.outbox.append({"from": mail_from, "to": list(rcpts), "data": b"".join(chunks).decode(errors="replace")})
                if self.store.silent_after_data:
                    time.sleep(self.store.silence_seconds)
                    return
                self._w("250 queued")
            elif cmd in ("RSET", "NOOP"):
                self._w("250 ok")
            elif cmd == "QUIT":
                if self.store.silent_at_quit:
                    time.sleep(self.store.silence_seconds)
                    return
                self._w(self.store.quit_reply or "221 bye")
                return
            else:
                self._w("502 not supported")


class _IMAP(socketserver.StreamRequestHandler):
    store: MailStore

    def _w(self, data: bytes) -> None:
        self.wfile.write(data)
        self.wfile.flush()

    def handle(self) -> None:
        self._w(b"* OK stub-imap ready\r\n")
        authed = False
        while True:
            raw = self.rfile.readline().decode(errors="replace").strip()
            if not raw:
                return
            tag, _, rest = raw.partition(" ")
            cmd, _, arg = rest.partition(" ")
            cmd = cmd.upper()
            if cmd == "CAPABILITY":
                self._w(b"* CAPABILITY IMAP4rev1\r\n" + tag.encode() + b" OK done\r\n")
            elif cmd == "LOGIN":
                m = re.findall(r'"([^"]*)"|(\S+)', arg)
                user, pw = (m[0][0] or m[0][1]), (m[1][0] or m[1][1])
                if self.store.users.get(user) == pw:
                    authed = True
                    self._w(tag.encode() + b" OK logged in\r\n")
                else:
                    self._w(tag.encode() + b" NO invalid credentials\r\n")
            elif cmd == "SELECT" and authed:
                n = len(self.store.inbox)
                self._w(f"* {n} EXISTS\r\n* 0 RECENT\r\n{tag} OK [READ-WRITE] selected\r\n".encode())
            elif cmd == "UID" and authed:
                sub, _, a2 = arg.partition(" ")
                sub = sub.upper()
                if sub == "SEARCH":
                    with self.store.lock:
                        uids = [m["uid"] for m in self.store.inbox if ("UNSEEN" not in a2.upper() or not m["seen"])]
                    self._w(("* SEARCH " + " ".join(map(str, uids))).strip().encode() + b"\r\n" + tag.encode() + b" OK done\r\n")
                elif sub == "FETCH":
                    uid = int(a2.split(" ", 1)[0])
                    with self.store.lock:
                        msg = next((m for m in self.store.inbox if m["uid"] == uid), None)
                    if msg is None:
                        self._w(tag.encode() + b" OK done\r\n")
                    else:
                        body = msg["raw"]
                        label = "BODY[]" if "PEEK" in a2.upper() else "RFC822"
                        size = f"RFC822.SIZE {len(body)} " if "RFC822.SIZE" in a2.upper() else ""
                        part = re.search(r"<(\d+)\.(\d+)>", a2)
                        if part:  # a partial fetch: only the bytes asked for come back
                            start, count = int(part.group(1)), int(part.group(2))
                            body, label = body[start:start + count], f"{label}<{start}>"
                        self._w(f"* {uid} FETCH (UID {uid} {size}{label} {{{len(body)}}}\r\n".encode() + body + b")\r\n" + tag.encode() + b" OK done\r\n")
                elif sub == "STORE":
                    uid = int(a2.split(" ", 1)[0])
                    with self.store.lock:
                        for m in self.store.inbox:
                            if m["uid"] == uid and "\\Seen" in a2:
                                m["seen"] = True
                    self._w(f"* {uid} FETCH (FLAGS (\\Seen))\r\n{tag} OK done\r\n".encode())
                else:
                    self._w(tag.encode() + b" BAD unsupported\r\n")
            elif cmd == "NOOP":
                self._w(tag.encode() + b" OK done\r\n")
            elif cmd == "LOGOUT":
                self._w(b"* BYE\r\n" + tag.encode() + b" OK bye\r\n")
                return
            else:
                self._w(tag.encode() + b" BAD unsupported\r\n")


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class StubMailServers:
    """Starts both servers on free local ports. Use as a context manager."""

    def __init__(self, store: MailStore | None = None, host: str = "127.0.0.1", smtp_port: int = 0, imap_port: int = 0):
        self.store = store or MailStore()
        smtp_h = type("SMTPH", (_SMTP,), {"store": self.store})
        imap_h = type("IMAPH", (_IMAP,), {"store": self.store})
        self._smtp, self._imap = _Server((host, smtp_port), smtp_h), _Server((host, imap_port), imap_h)
        self.host = host
        self.smtp_port, self.imap_port = self._smtp.server_address[1], self._imap.server_address[1]
        self._threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (self._smtp, self._imap)]

    def __enter__(self) -> StubMailServers:
        for t in self._threads:
            t.start()
        return self

    def __exit__(self, *exc) -> None:
        for s in (self._smtp, self._imap):
            s.shutdown()
            s.server_close()


if __name__ == "__main__":  # python -m mock.mail_servers
    with StubMailServers(smtp_port=2525, imap_port=1143) as srv:
        print(f"stub smtp on {srv.smtp_port}, stub imap on {srv.imap_port} (user demo, password demo-password). Ctrl C to stop.")
        threading.Event().wait()
