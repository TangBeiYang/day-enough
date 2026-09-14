"""Portable, versioned data backups. Never export credentials or sessions."""
import sqlite3
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

TABLES = ('tasks', 'plans', 'items', 'work_logs')


def export_data(db):
    return {'format': 'day-enough', 'version': 1,
            'default_minutes': int(db.execute("SELECT value FROM meta WHERE key='default_minutes'").fetchone()[0]),
            'tables': {name: [dict(row) for row in db.execute(f'SELECT * FROM {name}')] for name in TABLES}}


def restore_data(db, data):
    if not isinstance(data, dict) or data.get('format') != 'day-enough' or type(data.get('version')) is not int or data['version'] != 1:
        raise ValueError('不支持的备份版本')
    default = data.get('default_minutes')
    if type(default) is not int or not 0 <= default <= 960:
        raise ValueError('默认时间无效')
    tables = data.get('tables')
    if not isinstance(tables, dict) or set(tables) != set(TABLES):
        raise ValueError('缺少数据表')
    # Validate in a scratch database, including schema and foreign keys, before touching live data.
    scratch = sqlite3.connect(':memory:')
    try:
        scratch.executescript(Path(__file__).with_name('schema.sql').read_text())
        for name in TABLES:
            rows = tables[name]
            if not isinstance(rows, list) or len(rows) > 50000:
                raise ValueError('数据条数无效')
            info = scratch.execute(f'PRAGMA table_info({name})').fetchall()
            columns = [r[1] for r in info]
            numeric = {r[1] for r in info if r[2] == 'INTEGER'}
            for row in rows:
                if not isinstance(row, dict) or set(row) != set(columns):
                    raise ValueError(f'{name} 字段不匹配')
                for col in columns:
                    val = row[col]
                    if col in numeric:
                        if type(val) is not int or not 0 <= val <= 2**53:
                            raise ValueError('数值无效')
                    elif not isinstance(val, str) or len(val) > 2000:
                        raise ValueError('文本字段无效')
                    if col in ('id', 'task_id') and str(UUID(val)) != val:
                        raise ValueError('标识格式无效')
                    if col in ('due_date', 'day') and date.fromisoformat(val).isoformat() != val:
                        raise ValueError('日期无效')
                    if col in ('created_at', 'updated_at'):
                        datetime.fromisoformat(val)
                if name == 'tasks' and ((row['status'] == 'done' and row['remaining_minutes'] != 0) or (row['status'] == 'active' and row['remaining_minutes'] == 0)):
                    raise ValueError('任务状态和剩余时间不一致')
                scratch.execute(f'INSERT INTO {name} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})', [row[c] for c in columns])
        # Preserve account/secret/revision; replace only domain data within caller transaction.
        for name in reversed(TABLES):
            db.execute(f'DELETE FROM {name}')
        for name in TABLES:
            columns = [r[1] for r in scratch.execute(f'PRAGMA table_info({name})')]
            for row in scratch.execute(f'SELECT * FROM {name}'):
                db.execute(f'INSERT INTO {name} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})', tuple(row))
        db.execute("UPDATE meta SET value=? WHERE key='default_minutes'", (str(default),))
    finally:
        scratch.close()
