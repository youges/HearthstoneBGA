from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .model import Match


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS matches(
            id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT,
            hero_slot INTEGER, end_reason TEXT NOT NULL, placement INTEGER,
            rating_before INTEGER, rating_after INTEGER, rating_delta INTEGER,
            result_status TEXT NOT NULL, evidence_path TEXT)''')
        self.db.commit()

    def save(self, match: Match):
        record = asdict(match)
        record['rating_delta'] = match.rating_delta
        columns = list(record)
        names = ','.join(columns)
        placeholders = ','.join('?' for _ in columns)
        updates = ','.join(f'{c}=excluded.{c}' for c in columns if c != 'id')
        with self.db:
            self.db.execute(f'INSERT INTO matches({names}) VALUES({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}', list(record.values()))

    def recent(self, limit=200):
        return [dict(r) for r in self.db.execute('SELECT * FROM matches ORDER BY started_at DESC, rowid DESC LIMIT ?', (limit,))]

    def close(self):
        self.db.close()


class EventLog:
    def __init__(self, directory: Path, callback=None):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f'{datetime.now():%Y%m%d}.jsonl'
        self.callback = callback

    def emit(self, message, level='INFO', **fields):
        record = dict(time=now_iso(), level=level, message=message, **fields)
        with self.path.open('a', encoding='utf-8') as file:
            file.write(json.dumps(record, ensure_ascii=False) + '\n')
        if self.callback:
            self.callback(f'[{datetime.now():%H:%M:%S}] {level}  {message}')
