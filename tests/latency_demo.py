"""Both demo conversations over HTTP on a real PostgreSQL server, counted on the wire.

    CHAMAPRO_TEST_POSTGRES_URL=postgresql://postgres:pw@localhost:55432/postgres \
        python tests/latency_demo.py [--delay 0.2] [--json out.json]

It creates a scratch database on that server, migrates it, builds the demo into it, runs Wanjiru
and Njeri in English and Kikuyu through the API with typed answers, and drops the database. It
refuses Supabase, whatever is asked of it: the check is tests/safety.py's. No model is loaded and
nothing reaches Gemini; the classifier in models/ is the real one.

Three counts per turn:

    statements   what SQLAlchemy executed (before_cursor_execute), which is what the request log shows
    round trips  times the client waited for the server, seen by a TCP proxy between the two: every
                 statement, and every BEGIN, COMMIT and ping as well. This is the honest number.
    simulated    --delay seconds slept per statement by a SQLAlchemy hook, and the same again for each
                 round trip the hook cannot see, plus the time the statements really took: the
                 database's share of a turn from Nairobi

test_latency.py runs this and holds it to the limits.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import select
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "scripts")]


class Proxy(threading.Thread):
    """Forwards bytes and counts how often the client spoke after the server had: one count is one
    round trip, however many protocol messages or TCP segments it took. New connections are counted
    apart, since connecting costs several round trips of its own."""

    def __init__(self, target_host: str, target_port: int):
        super().__init__(daemon=True)
        self.target = (target_host, target_port)
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.round_trips = self.connections = 0
        self.seen: list[str] = []       # with --trace: what each round trip began with
        self.lock = threading.Lock()

    def run(self) -> None:
        while True:
            client, _ = self.listener.accept()
            with self.lock:
                self.connections += 1
            threading.Thread(target=self.pump, args=(client,), daemon=True).start()

    def pump(self, client: socket.socket) -> None:
        server = socket.create_connection(self.target)
        for s in (client, server):
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        last, handshake = None, True
        while True:
            ready, _, _ = select.select([client, server], [], [])
            for s in ready:
                data = s.recv(65536)
                if not data:
                    client.close()
                    server.close()
                    return
                if s is client:
                    # The connection's own start-up ends when the server says ReadyForQuery for
                    # the first time; what follows is the application's.
                    if last != "client" and not handshake:
                        with self.lock:
                            self.round_trips += 1
                            self.seen.append(data[5:90].decode("latin-1").replace("\0", " "))
                    last = "client"
                    server.sendall(data)
                else:
                    if handshake and data[-6:-5] == b"Z":
                        handshake = False
                    last = "server"
                    client.sendall(data)


def scratch_database(server_url: str):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from chamapro.config import _database_url
    base = make_url(_database_url(server_url))
    name = f"chamapro_latency_{secrets.token_hex(4)}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.exec_driver_sql(f"CREATE DATABASE {name}")

    def drop() -> None:
        with admin.connect() as c:
            c.exec_driver_sql(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.dispose()
    return base.set(database=name), drop


class Counted:
    """What the turn cost. The hook sleeps as the user's laptop would wait."""

    def __init__(self, proxy: Proxy, delay: float, trace: bool = False):
        self.proxy, self.delay, self.trace = proxy, delay, trace
        self.statements = 0
        self.started: dict[int, float] = {}
        self.statement_seconds = 0.0

    def before(self, conn, cursor, statement, parameters, context, executemany):
        self.statements += 1
        self.started[id(cursor)] = time.perf_counter()
        if self.delay:
            time.sleep(self.delay)

    def after(self, conn, cursor, statement, parameters, context, executemany):
        begun = self.started.pop(id(cursor), None)
        if begun is not None:
            self.statement_seconds += time.perf_counter() - begun

    def measure(self, call):
        statements, round_trips, connections = self.statements, self.proxy.round_trips, self.proxy.connections
        spent, begun = self.statement_seconds, time.perf_counter()
        self.proxy.seen.clear()
        result = call()
        if self.trace:
            print("\n".join(f"    {x}" for x in self.proxy.seen), "\n")
        wall = time.perf_counter() - begun
        n_statements, n_trips = self.statements - statements, self.proxy.round_trips - round_trips
        # A statement's time above already holds its delay; the BEGINs, COMMITs and pings do not.
        unseen = max(n_trips - n_statements, 0) * self.delay
        return result, {"statements": n_statements, "round_trips": n_trips,
                        "connections": self.proxy.connections - connections,
                        "database_s": round(self.statement_seconds - spent + unseen, 3), "wall_s": round(wall, 3)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--delay", type=float, default=0.2, help="seconds per statement (default %(default)s)")
    ap.add_argument("--json", type=Path, help="write the figures here as well")
    ap.add_argument("--trace", action="store_true", help="print the start of every round trip")
    a = ap.parse_args()

    server = os.environ.get("CHAMAPRO_TEST_POSTGRES_URL")
    if not server:
        sys.exit("set CHAMAPRO_TEST_POSTGRES_URL to a throwaway PostgreSQL server")

    # Before anything from chamapro reads them; .env must not choose any of this.
    from dotenv import dotenv_values
    from safety import unsafe_target
    why = unsafe_target(urls={}, storage={}, test_postgres=server, production=dotenv_values(ROOT / ".env").get("DATABASE_URL"),
                        data_dir=ROOT / "data")
    if why:
        sys.exit(f"refusing: {why}")
    os.environ.update(CHAMAPRO_UPLOADS=tempfile.mkdtemp(prefix="chamapro-latency-"), STORAGE_BACKEND="local", TTS_ENABLED="0",
                      CONVERSATION_GEMINI_LIVE="0", ASR_WARM="0", GOOGLE_CLIENT_ID="", DATABASE_URL="sqlite://")
    url, drop = scratch_database(server)
    proxy = Proxy(url.host or "localhost", url.port or 5432)
    proxy.start()
    through = url.set(host="127.0.0.1", port=proxy.port)
    os.environ["DATABASE_URL"] = through.render_as_string(hide_password=False)
    # safety.py has imported config already: read again, or the app's engine would be SQLite.
    import importlib

    import chamapro.config as cfg
    importlib.reload(cfg)
    try:
        return run(a, proxy, cfg)
    finally:
        from chamapro.api.db import engine
        engine.dispose()
        drop()


def run(a, proxy: Proxy, config) -> int:
    from alembic import command
    from fastapi.testclient import TestClient
    from sqlalchemy import event

    from chamapro.api import pipeline as pl
    from chamapro.api.db import alembic_config, engine
    from chamapro.api.main import app

    assert engine.url.get_backend_name() == "postgresql" and engine.url.port == proxy.port

    command.upgrade(alembic_config(engine.url.render_as_string(hide_password=False)), "head")
    import seed_demo
    built = seed_demo.seed_demo_db()
    passwords = built.passwords

    pl.transcribe.load_asr = lambda name, *x, **k: pl.transcribe.ASR(lambda *a2, **k2: {"text": "", "chunks": []}, "torch", "CPU", name)
    out: dict = {"conversations": {}, "polls": {}, "delay": a.delay}
    with TestClient(app, base_url="http://localhost") as boot:
        counted = Counted(proxy, a.delay, a.trace)
        event.listen(engine, "before_cursor_execute", counted.before)
        event.listen(engine, "after_cursor_execute", counted.after)

        def signed_in(login: str) -> TestClient:
            c = TestClient(app, base_url="http://localhost")
            r = c.post("/api/auth/login", json={"username": login, "password": passwords[login]})
            assert r.status_code == 200, r.text
            return c

        staff = signed_in("j.mwangi")
        admin = signed_in("s.achieng")
        from demo_scripts import SCRIPTS  # noqa: PLC0415
        for (name, language), script in SCRIPTS.items():
            login = {"Wanjiru Kamau": "w.kamau", "Njeri Mwangi": "n.mwangi"}[name]
            member = signed_in(login)
            rows = []
            r, cost = counted.measure(lambda: member.post("/api/conversations", json={"language": language}))
            assert r.status_code == 201, r.text
            cid = r.json()["conversation"]["id"]
            rows.append({"step": "start", "said": "G1 CONSENT", **cost})
            for words, want in script:
                r, cost = counted.measure(lambda: member.post(f"/api/conversations/{cid}/reply", data={"text": words}))
                assert r.status_code == 200, r.text
                said = [t["template_id"] for t in r.json()["bot_turns"]]
                assert said == want, (name, language, words, said)
                rows.append({"step": words, "said": " ".join(said), **cost})
            out["conversations"][f"{name} ({language})"] = rows
            if name == "Wanjiru Kamau" and language == "en":
                polls(out, counted, staff, member, cid)
            r = admin.post("/api/admin/demo-reset")
            assert r.status_code == 200 and not r.json()["problems"], r.text
    report(out)
    if a.json:
        a.json.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


def polls(out: dict, counted: Counted, staff, member, cid: int) -> None:
    """What sits behind each page and each poll while the conversation is on the screen."""
    def one(label: str, client, path: str, **kw) -> None:
        r, cost = counted.measure(lambda: client.get(path, **kw))
        assert r.status_code in (200, 304), (path, r.status_code, r.text)
        out["polls"][label] = {**cost, "status": r.status_code}
        return r

    one("/present list", staff, "/api/present/conversations")
    first = one("/present one, changed", staff, f"/api/present/conversations/{cid}")
    etag = first.headers.get("etag")
    one("/present one, unchanged", staff, f"/api/present/conversations/{cid}", headers={"If-None-Match": etag} if etag else {})
    one("chat stage poll", member, f"/api/conversations/{cid}/stage")
    one("chat transcript", member, f"/api/conversations/{cid}")
    one("chat carry on", member, "/api/conversations/current")
    one("my applications", member, "/api/me/applications")
    one("my sacco", member, "/api/me/sacco")
    one("signed in as", member, "/api/auth/me")


def report(out: dict) -> None:
    for name, rows in out["conversations"].items():
        print(f"\n{name}")
        print(f"  {'statements':>10} {'round trips':>11} {'database s':>10}  {'said':<14} answer")
        for r in rows:
            print(f"  {r['statements']:>10} {r['round_trips']:>11} {r['database_s']:>10.2f}  {r['said']:<14} {r['step']}"
                  + (f"  ({r['connections']} new connection)" if r["connections"] else ""))
    print("\npages and polls")
    for label, r in out["polls"].items():
        print(f"  {r['statements']:>10} {r['round_trips']:>11} {r['database_s']:>10.2f}  {label} [{r['status']}]")


if __name__ == "__main__":
    sys.exit(main())
