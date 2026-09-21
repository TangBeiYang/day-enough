"""Portable, versioned data backups. Never export credentials or sessions."""
import sqlite3
import json
from copy import deepcopy
from datetime import date, datetime
from uuid import UUID
from .db import init_db
from .recurrence import next_occurrence

TABLES = ('recurrences', 'tasks', 'plans', 'items', 'work_logs')


def export_data(db):
    return {'format': 'day-enough', 'version': 2,
            'default_minutes': int(db.execute("SELECT value FROM meta WHERE key='default_minutes'").fetchone()[0]),
            'tables': {name: [dict(row) for row in db.execute(f'SELECT * FROM {name}')] for name in TABLES}}


def restore_data(db, data):
    if not isinstance(data, dict) or data.get('format') != 'day-enough' or type(data.get('version')) is not int or data['version'] not in (1, 2):
        raise ValueError('不支持的备份版本')
    default = data.get('default_minutes')
    if type(default) is not int or not 0 <= default <= 960:
        raise ValueError('默认时间无效')
    tables = deepcopy(data.get('tables'))
    if data['version'] == 1:
        if not isinstance(tables, dict) or set(tables) != set(TABLES[1:]) or not isinstance(tables['tasks'], list):
            raise ValueError('旧版备份缺少数据表')
        tables['recurrences'] = []
        for task in tables['tasks']:
            if not isinstance(task, dict) or any(k in task for k in ('planned_date', 'recurrence_id', 'occurrence_date', 'missed_policy', 'missed')):
                raise ValueError('旧版任务字段无效')
            task.update(planned_date='', recurrence_id=None, occurrence_date='', missed_policy='carry', missed=0)
    if not isinstance(tables, dict) or set(tables) != set(TABLES):
        raise ValueError('缺少数据表')
    # Validate in a scratch database, including schema and foreign keys, before touching live data.
    scratch = sqlite3.connect(':memory:', isolation_level=None)
    try:
        init_db(scratch)
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
                    if col == 'recurrence_id' and val is None:
                        continue
                    if col in numeric:
                        if type(val) is not int or not 0 <= val <= 2**53:
                            raise ValueError('数值无效')
                    elif not isinstance(val, str) or len(val) > 2000:
                        raise ValueError('文本字段无效')
                    if col in ('id', 'task_id', 'recurrence_id') and str(UUID(val)) != val:
                        raise ValueError('标识格式无效')
                    if col in ('due_date', 'planned_date', 'occurrence_date') and val == '':
                        pass
                    elif col in ('due_date', 'day', 'planned_date', 'occurrence_date', 'start_date', 'next_date') and date.fromisoformat(val).isoformat() != val:
                        raise ValueError('日期无效')
                    if col in ('created_at', 'updated_at'):
                        datetime.fromisoformat(val)
                if name == 'tasks' and ((row['status'] == 'done' and row['remaining_minutes'] != 0) or (row['status'] == 'active' and row['remaining_minutes'] == 0)):
                    raise ValueError('任务状态和剩余时间不一致')
                if name == 'tasks':
                    if row['planned_date'] and row['due_date'] and row['planned_date'] > row['due_date']:
                        raise ValueError('计划日期晚于截止日期')
                    if row['recurrence_id']:
                        if not row['planned_date'] or not row['occurrence_date']:
                            raise ValueError('周期实例缺少日期')
                    elif row['occurrence_date'] or row['missed']:
                        raise ValueError('普通任务不能包含周期实例标记')
                    if row['missed'] and row['status'] != 'archived':
                        raise ValueError('漏做记录状态无效')
                if name == 'recurrences':
                    weekdays = json.loads(row['weekdays'])
                    if (not isinstance(weekdays, list) or len(weekdays) > 7
                            or any(type(d) is not int or not 0 <= d <= 6 for d in weekdays)
                            or (row['frequency'] == 'weekly' and not weekdays)):
                        raise ValueError('周期星期设置无效')
                    if row['start_date'] > '9998-12-31' or row['next_date'] > '9998-12-31':
                        raise ValueError('周期日期超出范围')
                    if row['frequency'] not in ('daily', 'weekly', 'monthly') or not 0 <= row['month_day'] <= 31:
                        raise ValueError('周期设置无效')
                    if next_occurrence(row['frequency'], weekdays, row['month_day'], row['start_date'], row['next_date']) != row['next_date']:
                        raise ValueError('下次日期与周期规则不一致')
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
