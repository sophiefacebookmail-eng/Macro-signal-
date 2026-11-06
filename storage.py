import sqlite3
from pathlib import Path

DB_PATH = Path("signals.sqlite3")

def connect():
    db = sqlite3.connect(DB_PATH)
    db.execute("CREATE TABLE IF NOT EXISTS subscribers (chat_id INTEGER PRIMARY KEY)")
    db.execute("""CREATE TABLE IF NOT EXISTS sent_signals (
        signal_key TEXT PRIMARY KEY, created_at INTEGER NOT NULL
    )""")
    db.commit()
    return db

def add_subscriber(chat_id):
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO subscribers(chat_id) VALUES(?)", (chat_id,))

def remove_subscriber(chat_id):
    with connect() as db:
        db.execute("DELETE FROM subscribers WHERE chat_id=?", (chat_id,))

def subscribers():
    with connect() as db:
        return [row[0] for row in db.execute("SELECT chat_id FROM subscribers")]

def first_time_signal(key, timestamp):
    with connect() as db:
        cur = db.execute("INSERT OR IGNORE INTO sent_signals(signal_key, created_at) VALUES(?,?)", (key, timestamp))
        return cur.rowcount == 1
