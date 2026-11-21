"""Tiny SQLite persistence: price-change log, alerts, live product state."""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(os.environ.get("PRICEPULSE_DB", Path(__file__).resolve().parent.parent / "artifacts" / "pricepulse.db"))
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript("""
        CREATE TABLE IF NOT EXISTS price_changes(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, sku TEXT,
            old_price REAL, new_price REAL, reason TEXT, source TEXT);
        CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, level TEXT, sku TEXT,
            kind TEXT, message TEXT);
        CREATE TABLE IF NOT EXISTS product_state(sku TEXT PRIMARY KEY, current_price REAL, stock REAL, comp_price REAL);
        CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
        """)
    return _conn


def reset():
    with _lock:
        c = conn()
        c.executescript("DELETE FROM price_changes; DELETE FROM alerts; DELETE FROM product_state; DELETE FROM kv;")
        c.commit()


def execute(sql, args=()):
    with _lock:
        c = conn()
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid


def query(sql, args=()):
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def log_price_change(sku, old, new, reason, source):
    execute("INSERT INTO price_changes(ts,sku,old_price,new_price,reason,source) VALUES(?,?,?,?,?,?)",
            (time.time(), sku, old, new, reason, source))


def log_alert(level, sku, kind, message):
    execute("INSERT INTO alerts(ts,level,sku,kind,message) VALUES(?,?,?,?,?)", (time.time(), level, sku, kind, message))


def save_state(sku, price, stock, comp):
    execute("INSERT OR REPLACE INTO product_state(sku,current_price,stock,comp_price) VALUES(?,?,?,?)",
            (sku, price, stock, comp))


def load_state():
    return {r["sku"]: r for r in query("SELECT * FROM product_state")}
