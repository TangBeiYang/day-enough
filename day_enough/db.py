import sqlite3
from pathlib import Path
from flask import current_app, g


def connect(path):
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=10000')
    return db


def get_db():
    if 'db' not in g:
        g.db = connect(current_app.config['DATABASE'])
    return g.db


def init_db(db):
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript(Path(__file__).with_name('schema.sql').read_text())
    # Additive migration preserves existing task ids, progress, plans and logs.
    db.execute('BEGIN IMMEDIATE')
    try:
        columns = {row[1] for row in db.execute('PRAGMA table_info(tasks)')}
        additions = {
            'planned_date': "TEXT NOT NULL DEFAULT ''",
            'recurrence_id': 'TEXT REFERENCES recurrences(id)',
            'occurrence_date': "TEXT NOT NULL DEFAULT ''",
            'missed_policy': "TEXT NOT NULL DEFAULT 'carry' CHECK(missed_policy IN ('skip','carry'))",
            'missed': 'INTEGER NOT NULL DEFAULT 0 CHECK(missed IN (0,1))',
        }
        for column, definition in additions.items():
            if column not in columns:
                db.execute(f'ALTER TABLE tasks ADD COLUMN {column} {definition}')
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS recurrence_occurrence ON tasks(recurrence_id,occurrence_date)')
        rule_columns = {row[1] for row in db.execute('PRAGMA table_info(recurrences)')}
        if 'due_day' not in rule_columns:
            db.execute('ALTER TABLE recurrences ADD COLUMN due_day INTEGER NOT NULL DEFAULT -1 CHECK(due_day BETWEEN -1 AND 31)')
        db.execute('PRAGMA user_version=3')
        db.commit()
    except Exception:
        db.rollback()
        raise


def value(db, key):
    row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    return row['value'] if row else None


def set_value(db, key, val):
    db.execute('INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(val)))
