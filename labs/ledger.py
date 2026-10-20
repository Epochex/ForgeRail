import sqlite3
from pathlib import Path

class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, value INTEGER NOT NULL, offset INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS checkpoints (partition INTEGER PRIMARY KEY, offset INTEGER NOT NULL)')

    def connect(self):
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA synchronous=FULL')
        return db

    def apply(self, event, offset, partition=0):
        with self.connect() as db:
            cursor = db.execute('INSERT OR IGNORE INTO events VALUES (?, ?, ?)', (event['id'], event['value'], offset))
            db.execute('INSERT INTO checkpoints VALUES (?, ?) ON CONFLICT(partition) DO UPDATE SET offset=max(offset,excluded.offset)', (partition, offset))
            return cursor.rowcount == 1

    def summary(self):
        with self.connect() as db:
            unique, total = db.execute('SELECT count(*),coalesce(sum(value),0) FROM events').fetchone()
            checkpoint = db.execute('SELECT coalesce(max(offset),-1) FROM checkpoints').fetchone()[0]
            return dict(unique=unique, total=total, checkpoint=checkpoint)
