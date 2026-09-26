import hashlib
import json
import secrets
import sqlite3
import time
import unicodedata
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo
from flask import Blueprint, abort, current_app, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash
from .db import connect, get_db, get_registry_db, init_db, user_db_path, value, set_value
from .capacity import read_capacity, validate_capacity, minutes_on
from .planner import recommend, risks
from .recurrence import next_occurrence, sync_recurring, cycle_start

bp = Blueprint('api', __name__, url_prefix='/api')
LEVELS = ('low', 'medium', 'high')


def today():
    override = current_app.config.get('TODAY')
    return override if override else datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()


def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')


def integer(val, name, low=0, high=600000):
    if type(val) is not int or not low <= val <= high:
        abort(400, f'{name}须为 {low}–{high} 之间的整数。')
    return val


def text_field(data, name, maximum, required=True):
    val = data.get(name, '')
    if not isinstance(val, str) or len(val.strip()) > maximum or (required and not val.strip()):
        abort(400, f'{name} 内容无效（最多 {maximum} 字）。')
    return val.strip()


def optional_date_field(val, label='截止日期'):
    if val == '':
        return ''
    try:
        if not isinstance(val, str) or date.fromisoformat(val).isoformat() != val:
            raise ValueError()
    except ValueError:
        abort(400, f'{label}须留空或使用 YYYY-MM-DD 格式。')
    return val


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, '请求须为 JSON 对象。')
    return data


def csrf():
    token = session.get('csrf', '')
    if not token or not secrets.compare_digest(token, request.headers.get('X-CSRF-Token', '')):
        abort(403, '页面会话已变化，请刷新后重试。')


def authenticated():
    user_id = session.get('user_id')
    if not user_id or not get_registry_db().execute('SELECT 1 FROM users WHERE id=?', (user_id,)).fetchone():
        return False
    return session.get('auth_version') == value(get_db(), 'auth_version')


def require_auth():
    if not authenticated():
        abort(401, '请先登录。')


def planning_context(db, day):
    recurrences = [dict(row) for row in db.execute('SELECT * FROM recurrences ORDER BY created_at DESC,id')]
    for rule in recurrences:
        rule['weekdays'] = json.loads(rule['weekdays'])
    stages = [dict(row) for row in db.execute('SELECT * FROM stages ORDER BY start_date DESC,created_at DESC,id')]
    for stage in stages:
        stage['targets'] = [dict(row) for row in db.execute('''SELECT g.task_id,g.mode,g.target_minutes,g.position,
            COALESCE(SUM(l.minutes),0) AS progress_minutes,t.status AS task_status
            FROM stage_targets g JOIN tasks t ON t.id=g.task_id
            LEFT JOIN work_logs l ON l.task_id=g.task_id AND l.day>=?
            WHERE g.stage_id=? GROUP BY g.task_id ORDER BY g.position,g.task_id''',
            (stage['start_date'], stage['id']))]
        for target in stage['targets']:
            target['completed'] = target['task_status'] == 'done' or (
                target['mode'] == 'minutes' and target['progress_minutes'] >= target['target_minutes'])
        stage['completed_count'] = sum(target['completed'] for target in stage['targets'])
        stage['overdue_count'] = (len(stage['targets']) - stage['completed_count']
                                  if stage['status'] == 'active' and day > stage['end_date'] else 0)
    return recurrences, stages


def planning_tasks(db, tasks):
    latest = dict(db.execute('SELECT task_id,MAX(day) FROM work_logs GROUP BY task_id'))
    return [dict(task, _last_work_day=latest.get(task['id']) or task['created_at'][:10])
            for task in tasks]


def snapshot(db):
    day = today()
    tasks = [dict(row) for row in db.execute('SELECT * FROM tasks ORDER BY created_at DESC,id')]
    plan_row = db.execute('SELECT * FROM plans WHERE day=?', (day,)).fetchone()
    plan = dict(plan_row) if plan_row else None
    items = [dict(row) for row in db.execute('''SELECT i.*, t.title, t.due_date, t.energy,
        t.planned_date, t.recurrence_id, t.occurrence_date, t.missed,
        t.remaining_minutes, t.next_step, t.status AS task_status
        FROM items i JOIN tasks t ON t.id=i.task_id WHERE i.day=? ORDER BY i.position,i.id''', (day,))]
    totals = db.execute("SELECT COALESCE(SUM(minutes),0), COALESCE(SUM(CASE WHEN energy='high' THEN minutes ELSE 0 END),0) FROM work_logs WHERE day=?", (day,)).fetchone()
    default = int(value(db, 'default_minutes'))
    weekly, overrides = read_capacity(db)
    recurrences, stages = planning_context(db, day)
    allocations = {i['task_id']: min(i['remaining_minutes'], max(0, i['planned_minutes'] - i['done_minutes']))
                   for i in items if i['status'] == 'pending' and i['task_status'] == 'active'}
    today_budget = plan['budget'] if plan else minutes_on(date.fromisoformat(day), default, weekly, overrides)
    warnings = risks(planning_tasks(db, tasks), date.fromisoformat(day), default,
                     today_budget, totals[0],
                     plan['energy'] if plan else 'medium', totals[1], allocations,
                     weekly_minutes=weekly, date_overrides=overrides,
                     stages=stages, recurrences=recurrences,
                     locked_today=bool(plan)) if tasks else []
    if plan and totals[0] + sum(allocations.values()) > plan['budget']:
        over = totals[0] + sum(allocations.values()) - plan['budget']
        warnings.insert(0, f'已投入与待做安排合计超过今日预算 {over} 分钟；你可以按自己的节奏决定。')
    handled = {i['task_id'] for i in items}
    unplanned = [t['id'] for t in tasks if t['status'] == 'active' and t['id'] not in handled]
    return {'day': day, 'revision': int(value(db, 'revision')), 'tasks': tasks,
            'recurrences': recurrences, 'stages': stages, 'unplanned_scheduled': unplanned,
            'plan': plan, 'items': items, 'worked_minutes': totals[0],
            'remaining_planned': sum(allocations.values()), 'warnings': warnings,
            'settings': {'default_minutes': default, 'weekly_minutes': weekly,
                         'date_overrides': overrides, 'timezone': 'Asia/Shanghai'}}


def mutation(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        require_auth()
        csrf()
        data = payload()
        db = get_db()
        db.execute('BEGIN IMMEDIATE')
        try:
            # Recheck after acquiring lock, e.g. concurrent password changes.
            require_auth()
            if data.get('day') != today():
                abort(409, '日期已变化，请刷新页面后再操作。')
            integer(data.get('revision'), '数据版本', 0, 2**53)
            token = request.headers.get('Idempotency-Key', '')
            if not 16 <= len(token) <= 128:
                abort(400, '缺少有效的操作标识。')
            fingerprint = hashlib.sha256((request.path + json.dumps(data, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
            receipt = db.execute('SELECT fingerprint FROM receipts WHERE id=?', (token,)).fetchone()
            if receipt:
                if receipt['fingerprint'] != fingerprint:
                    abort(409, '操作标识已使用，请刷新页面。')
            else:
                if data['revision'] != int(value(db, 'revision')):
                    abort(409, '其他页面已更新数据。请刷新，核对最新内容后再提交。')
                sync_recurring(db, today(), now())
                fn(db, data, *args, **kwargs)
                sync_recurring(db, today(), now())
                set_value(db, 'revision', data['revision'] + 1)
                db.execute('INSERT INTO receipts VALUES (?,?)', (token, fingerprint))
            result = snapshot(db)
            db.commit()
            return jsonify(result)
        except Exception:
            db.rollback()
            raise
    return wrapped


@bp.get('/session')
def get_session():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_hex(32)
    logged_in = bool(authenticated())
    username = None
    if logged_in:
        username = get_registry_db().execute('SELECT username FROM users WHERE id=?',
                                             (session['user_id'],)).fetchone()['username']
    return jsonify(authenticated=logged_in, configured=bool(value(get_registry_db(), 'password_hash')),
                   username=username, csrf=session['csrf'])


def username_field(data):
    raw = data.get('username')
    if not isinstance(raw, str):
        abort(400, '用户名须为 3–32 个字符，可使用汉字、字母、数字、下划线和短横线。')
    name = unicodedata.normalize('NFKC', raw.strip()).casefold()
    if not 3 <= len(name) <= 32 or not all(c.isalnum() or c in '_-' for c in name):
        abort(400, '用户名须为 3–32 个字符，可使用汉字、字母、数字、下划线和短横线。')
    return name


def record_attempt(db):
    stamp = time.time()
    ip = request.remote_addr or 'unknown'
    db.execute('DELETE FROM login_attempts WHERE at<?', (stamp - 300,))
    if db.execute('SELECT COUNT(*) FROM login_attempts WHERE ip=?', (ip,)).fetchone()[0] >= 10:
        abort(429, '尝试次数较多，请 5 分钟后重试。')
    db.execute('INSERT INTO login_attempts VALUES (?,?)', (ip, stamp))


def sign_in(user_id, version):
    session.clear()
    session.permanent = True
    session.update(user_id=user_id, auth_version=version, csrf=secrets.token_hex(32))
    return jsonify(csrf=session['csrf'])


@bp.post('/login')
def login():
    csrf()
    data = payload()
    username = username_field(data)
    password = data.get('password')
    if not isinstance(password, str) or len(password) > 256:
        abort(400, '密码无效。')
    registry = get_registry_db()
    registry.execute('BEGIN IMMEDIATE')
    try:
        record_attempt(registry)
        row = registry.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        registry.commit()
    except Exception:
        registry.rollback()
        raise
    if not row:
        abort(401, '用户名或密码不正确。')
    if row['id'] != 'owner' and not Path(user_db_path(row['id'])).is_file():
        abort(503, '账号数据暂时不可用，请联系管理员检查备份。')
    db = registry if row['id'] == 'owner' else connect(user_db_path(row['id']))
    try:
        stored = value(db, 'password_hash')
        login_version = value(db, 'auth_version')
    finally:
        if db is not registry:
            db.close()
    if not stored or not check_password_hash(stored, password):
        abort(401, '用户名或密码不正确。')
    return sign_in(row['id'], login_version)


@bp.post('/register')
def register_user():
    csrf()
    data = payload()
    username = username_field(data)
    password = data.get('password')
    invite_code = data.get('invite_code')
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        abort(400, '密码须为 12–256 个字符。')
    if not isinstance(invite_code, str) or len(invite_code) > 256:
        abort(400, '邀请码无效。')
    registry = get_registry_db()
    registry.execute('BEGIN IMMEDIATE')
    try:
        record_attempt(registry)
        registry.commit()
    except Exception:
        registry.rollback()
        raise
    registry.execute('BEGIN IMMEDIATE')
    new_path = None
    try:
        invite_hash = value(registry, 'invite_code_hash')
        if not invite_hash:
            abort(503, '当前未开放注册，请联系管理员设置邀请码。')
        if not check_password_hash(invite_hash, invite_code):
            abort(403, '邀请码不正确。')
        if registry.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone():
            abort(409, '该用户名已被使用。')
        user_id = uuid4().hex
        directory = Path(user_db_path(user_id)).parent
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        new_path = Path(user_db_path(user_id))
        user_db = connect(new_path)
        try:
            init_db(user_db)
            user_db.execute('BEGIN IMMEDIATE')
            set_value(user_db, 'password_hash', generate_password_hash(password))
            user_db.commit()
        finally:
            user_db.close()
        new_path.chmod(0o600)
        registry.execute('INSERT INTO users VALUES (?,?,?)', (user_id, username, now()))
        registry.commit()
    except Exception:
        registry.rollback()
        if new_path:
            for suffix in ('', '-wal', '-shm'):
                Path(str(new_path) + suffix).unlink(missing_ok=True)
        raise
    return sign_in(user_id, '0')


@bp.post('/logout')
def logout():
    csrf()
    session.clear()
    return jsonify(ok=True)


@bp.get('/state')
def state():
    require_auth()
    db = get_db()
    db.execute('BEGIN IMMEDIATE')
    try:
        if sync_recurring(db, today(), now()):
            set_value(db, 'revision', int(value(db, 'revision')) + 1)
        result = snapshot(db)
        db.commit()
        return jsonify(result)
    except Exception:
        db.rollback()
        raise


def task_fields(data):
    title = text_field(data, 'title', 120)
    step = text_field(data, 'next_step', 500, False)
    due = optional_date_field(data.get('due_date'))
    if data.get('energy') not in LEVELS or data.get('consequence') not in LEVELS:
        abort(400, '请选择有效的精力等级和后果严重度。')
    remaining = integer(data.get('remaining_minutes'), '剩余分钟', 0)
    return title, due, data['consequence'], data['energy'], remaining, step


def planned_date_field(data, due, default=''):
    planned = optional_date_field(data.get('planned_date', default), '计划完成日期')
    if planned and due and planned > due:
        abort(400, '计划完成日期不能晚于截止日期。')
    return planned


def task_by_id(db, task_id):
    task = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
    if not task:
        abort(404, '任务不存在。')
    return task


def settle_items(db, task_id):
    db.execute("UPDATE items SET status='done' WHERE task_id=? AND day=? AND status='pending'", (task_id, today()))


@bp.post('/tasks')
@mutation
def add_task(db, data):
    fields = task_fields(data)
    if fields[4] <= 0:
        abort(400, '新任务的预计用时须大于 0。')
    planned = planned_date_field(data, fields[1])
    stage_id = data.get('stage_id')
    stage = stage_by_id(db, stage_id, {'version': data.get('stage_version')}) if stage_id else None
    if stage and stage['status'] != 'active':
        abort(400, '已结束追踪的阶段计划不能添加任务。')
    task_id = str(uuid4())
    db.execute('''INSERT INTO tasks(id,title,due_date,consequence,energy,remaining_minutes,next_step,created_at,updated_at,planned_date)
                  VALUES (?,?,?,?,?,?,?,?,?,?)''', (task_id, *fields, now(), now(), planned))
    if stage:
        position = db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM stage_targets WHERE stage_id=?', (stage_id,)).fetchone()[0]
        db.execute('INSERT INTO stage_targets VALUES (?,?,?,?,?)', (stage_id, task_id, 'complete', 0, position))
        db.execute('UPDATE stages SET version=version+1,updated_at=? WHERE id=?', (now(), stage_id))


@bp.post('/tasks/<task_id>')
@mutation
def edit_task(db, data, task_id):
    task = task_by_id(db, task_id)
    if data.get('version') != task['version']:
        abort(409, '任务已有新版本，请刷新。')
    fields = task_fields(data)
    planned = planned_date_field(data, fields[1], task['planned_date'])
    if task['recurrence_id'] and not planned:
        abort(400, '周期任务的本次计划完成日期不能为空。')
    status = data.get('status', task['status'])
    if status not in ('active', 'done', 'archived'):
        abort(400, '任务状态无效。')
    if fields[4] == 0 and status == 'active':
        status = 'done'
    if status == 'done':
        fields = (*fields[:4], 0, fields[5])
    db.execute('''UPDATE tasks SET title=?,due_date=?,consequence=?,energy=?,remaining_minutes=?,next_step=?,
                  status=?,version=version+1,updated_at=?,planned_date=?,missed=0 WHERE id=?''', (*fields, status, now(), planned, task_id))
    if status != 'active':
        settle_items(db, task_id)


def remove_task_data(db, task_id):
    db.execute('DELETE FROM stage_targets WHERE task_id=?', (task_id,))
    db.execute('DELETE FROM items WHERE task_id=?', (task_id,))
    db.execute('DELETE FROM work_logs WHERE task_id=?', (task_id,))
    db.execute('DELETE FROM tasks WHERE id=?', (task_id,))


@bp.post('/tasks/<task_id>/delete')
@mutation
def delete_task(db, data, task_id):
    task = task_by_id(db, task_id)
    if data.get('version') != task['version']:
        abort(409, '任务已有新版本，请刷新。')
    if data.get('confirmation') != '删除':
        abort(400, '请输入「删除」确认。')
    if task['recurrence_id']:
        db.execute('INSERT OR IGNORE INTO suppressed_occurrences VALUES (?,?)',
                   (task['recurrence_id'], task['occurrence_date']))
    remove_task_data(db, task_id)


@bp.post('/recurrences/<rule_id>/delete')
@mutation
def delete_recurrence(db, data, rule_id):
    recurrence_by_id(db, rule_id, data)
    if data.get('confirmation') != '删除':
        abort(400, '请输入「删除」确认。')
    for row in db.execute('SELECT id FROM tasks WHERE recurrence_id=?', (rule_id,)).fetchall():
        remove_task_data(db, row['id'])
    db.execute('DELETE FROM suppressed_occurrences WHERE recurrence_id=?', (rule_id,))
    db.execute('DELETE FROM recurrences WHERE id=?', (rule_id,))


def stage_by_id(db, stage_id, data):
    stage = db.execute('SELECT * FROM stages WHERE id=?', (stage_id,)).fetchone()
    if not stage:
        abort(404, '阶段计划不存在。')
    if data.get('version') != stage['version']:
        abort(409, '阶段计划已有新版本，请刷新。')
    return stage


def stage_fields(data):
    title = text_field(data, 'title', 120)
    description = text_field(data, 'description', 500, False)
    start = optional_date_field(data.get('start_date'), '开始日期')
    end = optional_date_field(data.get('end_date'), '结束日期')
    if not start or not end or start > end or end > '9998-12-31':
        abort(400, '请填写有效的阶段起止日期，结束日期不能早于开始日期。')
    return title, start, end, description


@bp.post('/stages')
@mutation
def add_stage(db, data):
    fields = stage_fields(data)
    db.execute('''INSERT INTO stages(id,title,start_date,end_date,description,created_at,updated_at)
                  VALUES (?,?,?,?,?,?,?)''', (str(uuid4()), *fields, now(), now()))


@bp.post('/stages/<stage_id>')
@mutation
def edit_stage(db, data, stage_id):
    stage_by_id(db, stage_id, data)
    fields = stage_fields(data)
    db.execute('''UPDATE stages SET title=?,start_date=?,end_date=?,description=?,
                  version=version+1,updated_at=? WHERE id=?''', (*fields, now(), stage_id))


@bp.post('/stages/<stage_id>/status')
@mutation
def stage_status(db, data, stage_id):
    stage_by_id(db, stage_id, data)
    status = data.get('status')
    if status not in ('active', 'closed'):
        abort(400, '阶段计划状态无效。')
    db.execute('UPDATE stages SET status=?,version=version+1,updated_at=? WHERE id=?',
               (status, now(), stage_id))


@bp.post('/stages/<stage_id>/delete')
@mutation
def delete_stage(db, data, stage_id):
    stage_by_id(db, stage_id, data)
    if data.get('confirmation') != '删除':
        abort(400, '请输入「删除」确认。')
    db.execute('DELETE FROM stage_targets WHERE stage_id=?', (stage_id,))
    db.execute('DELETE FROM stages WHERE id=?', (stage_id,))


@bp.post('/stages/<stage_id>/targets')
@mutation
def save_stage_target(db, data, stage_id):
    stage = stage_by_id(db, stage_id, data)
    if stage['status'] != 'active':
        abort(400, '请先恢复追踪，再调整目标。')
    task_id = data.get('task_id')
    if not isinstance(task_id, str):
        abort(400, '请选择任务。')
    task = task_by_id(db, task_id)
    existing = db.execute('SELECT * FROM stage_targets WHERE stage_id=? AND task_id=?', (stage_id, task_id)).fetchone()
    if not existing and task['status'] != 'active':
        abort(400, '只能添加待推进的任务。')
    if task['recurrence_id'] and task['missed_policy'] == 'skip':
        abort(400, '这次周期任务设置为漏做不补做，不能加入可顺延的阶段计划。请先将规则改为保留待办。')
    mode = data.get('mode')
    if mode not in ('complete', 'minutes'):
        abort(400, '请选择完成任务或投入指定分钟。')
    minutes = integer(data.get('target_minutes'), '目标分钟', 0 if mode == 'complete' else 1)
    if mode == 'complete' and minutes != 0:
        abort(400, '完成整个任务无需填写目标分钟。')
    position = existing['position'] if existing else db.execute(
        'SELECT COALESCE(MAX(position),-1)+1 FROM stage_targets WHERE stage_id=?', (stage_id,)).fetchone()[0]
    db.execute('''INSERT INTO stage_targets VALUES (?,?,?,?,?) ON CONFLICT(stage_id,task_id)
                  DO UPDATE SET mode=excluded.mode,target_minutes=excluded.target_minutes''',
               (stage_id, task_id, mode, minutes, position))
    db.execute('UPDATE stages SET version=version+1,updated_at=? WHERE id=?', (now(), stage_id))


@bp.post('/stages/<stage_id>/targets/<task_id>/remove')
@mutation
def remove_stage_target(db, data, stage_id, task_id):
    stage_by_id(db, stage_id, data)
    if not db.execute('SELECT 1 FROM stage_targets WHERE stage_id=? AND task_id=?', (stage_id, task_id)).fetchone():
        abort(404, '阶段目标不存在。')
    db.execute('DELETE FROM stage_targets WHERE stage_id=? AND task_id=?', (stage_id, task_id))
    db.execute('UPDATE stages SET version=version+1,updated_at=? WHERE id=?', (now(), stage_id))


def recurrence_fields(data, previous=None):
    fields = task_fields({**data, 'due_date': ''})
    if fields[4] <= 0:
        abort(400, '每次预计用时须大于 0。')
    frequency = data.get('frequency')
    weekdays = data.get('weekdays', [])
    if frequency not in ('daily', 'weekly', 'monthly'):
        abort(400, '请选择每天、每周或每月。')
    if (not isinstance(weekdays, list) or len(weekdays) > 7
            or any(type(d) is not int or not 0 <= d <= 6 for d in weekdays)):
        abort(400, '星期设置无效。')
    if frequency == 'weekly' and not weekdays:
        abort(400, '每周任务至少选择一个星期。')
    month_day = integer(data.get('month_day', 0), '每月日期', 0, 31)
    start = optional_date_field(data.get('planned_date', previous['start_date'] if previous else ''), '开始日期')
    if not start or start > '9998-12-31':
        abort(400, '请填写有效的开始日期（不超过 9998 年）。')
    if previous and start != previous['start_date']:
        abort(400, '已有周期规则的开始日期不能修改，可调整周期或暂停。')
    if not previous and start < today():
        abort(400, '新周期任务的开始日期不能早于今天。')
    policy = data.get('missed_policy', 'skip')
    if policy not in ('skip', 'carry'):
        abort(400, '请选择漏做后不补做或保留待办。')
    due = data.get('due_on_planned', False)
    if type(due) not in (bool, int) or due not in (0, 1):
        abort(400, '截止设置无效。')
    due_day = integer(data.get('due_day', -1), '周期截止日期', -1, 31)
    if (frequency == 'daily' and due_day != -1) or (frequency == 'weekly' and due_day > 6) or (due and due_day != -1):
        abort(400, '截止日期与重复频率不匹配。')
    weekdays = sorted(set(weekdays)) if frequency == 'weekly' else []
    month_day = month_day if frequency == 'monthly' else 0
    next_day = next_occurrence(frequency, weekdays, month_day,
                               start if previous else cycle_start(frequency, start),
                               today() if previous else cycle_start(frequency, today()))
    return (fields[0], fields[2], fields[3], fields[4], fields[5], frequency,
            json.dumps(weekdays), month_day, start, next_day, int(due), policy, due_day)


@bp.post('/recurrences')
@mutation
def add_recurrence(db, data):
    fields = recurrence_fields(data)
    db.execute('''INSERT INTO recurrences
        (id,title,consequence,energy,minutes,next_step,frequency,weekdays,month_day,
         start_date,next_date,due_on_planned,missed_policy,due_day,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (str(uuid4()), *fields, now(), now()))


def recurrence_by_id(db, rule_id, data):
    rule = db.execute('SELECT * FROM recurrences WHERE id=?', (rule_id,)).fetchone()
    if not rule:
        abort(404, '周期规则不存在。')
    if data.get('version') != rule['version']:
        abort(409, '周期规则已有新版本，请刷新。')
    return rule


@bp.post('/recurrences/<rule_id>')
@mutation
def edit_recurrence(db, data, rule_id):
    rule = recurrence_by_id(db, rule_id, data)
    fields = recurrence_fields(data, rule)
    db.execute('''UPDATE recurrences SET title=?,consequence=?,energy=?,minutes=?,next_step=?,
        frequency=?,weekdays=?,month_day=?,start_date=?,next_date=?,due_on_planned=?,missed_policy=?,due_day=?,
        version=version+1,updated_at=? WHERE id=?''', (*fields, now(), rule_id))


@bp.post('/recurrences/<rule_id>/status')
@mutation
def recurrence_status(db, data, rule_id):
    rule = recurrence_by_id(db, rule_id, data)
    status = data.get('status')
    if status not in ('active', 'paused'):
        abort(400, '周期规则状态无效。')
    next_day = rule['next_date']
    if rule['status'] == 'paused' and status == 'active':
        next_day = next_occurrence(rule['frequency'], json.loads(rule['weekdays']),
                                   rule['month_day'], rule['start_date'], today())
    db.execute('UPDATE recurrences SET status=?,next_date=?,version=version+1,updated_at=? WHERE id=?',
               (status, next_day, now(), rule_id))


@bp.post('/tasks/<task_id>/work')
@mutation
def work(db, data, task_id):
    task = task_by_id(db, task_id)
    if task['status'] != 'active':
        abort(400, '只能为进行中的任务记录投入。')
    minutes = integer(data.get('minutes'), '投入分钟', 1, 960)
    db.execute('INSERT INTO work_logs VALUES (?,?,?,?,?,?)', (str(uuid4()), task_id, today(), minutes, task['energy'], now()))
    remaining = max(0, task['remaining_minutes'] - minutes)
    db.execute('''UPDATE tasks SET remaining_minutes=?,worked_minutes=worked_minutes+?,status=?,
                  version=version+1,updated_at=? WHERE id=?''',
               (remaining, minutes, 'active' if remaining else 'done', now(), task_id))
    db.execute('''UPDATE items SET done_minutes=done_minutes+?,
                  status=CASE WHEN done_minutes+?>=planned_minutes OR ?=0 THEN 'done' ELSE status END
                  WHERE task_id=? AND day=?''', (minutes, minutes, remaining, task_id, today()))


@bp.post('/plan')
@mutation
def make_plan(db, data):
    budget = integer(data.get('budget'), '今日可用分钟', 0, 960)
    energy = data.get('energy')
    if energy not in LEVELS:
        abort(400, '请选择今日状态。')
    day = today()
    db.execute('''INSERT INTO plans VALUES (?,?,?,?) ON CONFLICT(day)
                  DO UPDATE SET budget=excluded.budget,energy=excluded.energy''', (day, budget, energy, now()))
    previous = [dict(row) for row in db.execute('SELECT * FROM items WHERE day=?', (day,))]
    excluded = {i['task_id'] for i in previous if i['status'] in ('done', 'skipped')}
    # Keep already completed and skipped rows, plus progress on partial rows.
    db.execute("DELETE FROM items WHERE day=? AND status='pending' AND done_minutes=0", (day,))
    db.execute("UPDATE items SET planned_minutes=done_minutes,status='done' WHERE day=? AND status='pending'", (day,))
    tasks = [dict(row) for row in db.execute('SELECT * FROM tasks')]
    totals = db.execute("SELECT COALESCE(SUM(minutes),0),COALESCE(SUM(CASE WHEN energy='high' THEN minutes ELSE 0 END),0) FROM work_logs WHERE day=?", (day,)).fetchone()
    weekly, overrides = read_capacity(db)
    recurrences, stages = planning_context(db, day)
    picks = recommend(planning_tasks(db, tasks), date.fromisoformat(day), budget, energy,
                      totals[0], totals[1], excluded,
                      default_minutes=int(value(db, 'default_minutes')),
                      weekly_minutes=weekly, date_overrides=overrides,
                      stages=stages, recurrences=recurrences)
    for position, pick in enumerate(picks):
        existing = db.execute('SELECT * FROM items WHERE day=? AND task_id=?', (day, pick['task_id'])).fetchone()
        if existing:
            db.execute("UPDATE items SET planned_minutes=done_minutes+?,status='pending',reason=?,position=? WHERE id=?",
                       (pick['planned_minutes'], pick['reason'], position, existing['id']))
        else:
            db.execute('INSERT INTO items(id,day,task_id,planned_minutes,reason,position) VALUES (?,?,?,?,?,?)',
                       (str(uuid4()), day, pick['task_id'], pick['planned_minutes'], pick['reason'], position))


@bp.post('/plan/manual')
@mutation
def make_manual_plan(db, data):
    budget = integer(data.get('budget'), '今日可用分钟', 0, 960)
    energy = data.get('energy')
    if energy not in LEVELS:
        abort(400, '请选择今日状态。')
    choices = data.get('items')
    if not isinstance(choices, list) or len(choices) > 500:
        abort(400, '手动安排列表无效。')
    seen = set()
    picks = []
    for choice in choices:
        if not isinstance(choice, dict) or set(choice) != {'task_id', 'minutes'}:
            abort(400, '手动安排内容无效。')
        task_id = choice['task_id']
        if not isinstance(task_id, str) or task_id in seen:
            abort(400, '同一任务只能安排一次。')
        seen.add(task_id)
        task = task_by_id(db, task_id)
        if task['status'] != 'active' or task['remaining_minutes'] <= 0:
            abort(400, '只能安排待推进的任务。')
        minutes = integer(choice['minutes'], '手动安排分钟', 1, 600000)
        if minutes > task['remaining_minutes']:
            abort(400, '安排分钟不能超过任务剩余估计。')
        picks.append((task_id, minutes))
    day = today()
    db.execute('''INSERT INTO plans VALUES (?,?,?,?) ON CONFLICT(day)
                  DO UPDATE SET budget=excluded.budget,energy=excluded.energy''', (day, budget, energy, now()))
    previous = {row['task_id']: dict(row) for row in db.execute('SELECT * FROM items WHERE day=? ORDER BY position,id', (day,))}
    selected = set(seen)
    for task_id, item in previous.items():
        if task_id in selected or item['status'] != 'pending':
            continue
        if item['done_minutes']:
            db.execute("UPDATE items SET planned_minutes=done_minutes,status='done' WHERE id=?", (item['id'],))
        else:
            db.execute('DELETE FROM items WHERE id=?', (item['id'],))
    for position, (task_id, minutes) in enumerate(picks):
        item = previous.get(task_id)
        reason = '自己安排 · 按自己的节奏推进'
        if item:
            db.execute('''UPDATE items SET planned_minutes=done_minutes+?,status='pending',
                          reason=?,position=? WHERE id=?''', (minutes, reason, position, item['id']))
        else:
            db.execute('''INSERT INTO items(id,day,task_id,planned_minutes,reason,position)
                          VALUES (?,?,?,?,?,?)''', (str(uuid4()), day, task_id, minutes, reason, position))
    kept = [item for item in previous.values() if item['task_id'] not in selected and
            (item['status'] in ('done', 'skipped') or item['done_minutes'] > 0)]
    for position, item in enumerate(kept, start=len(picks)):
        db.execute('UPDATE items SET position=? WHERE id=?', (position, item['id']))


@bp.post('/items/<item_id>/skip')
@mutation
def skip(db, data, item_id):
    item = db.execute('SELECT * FROM items WHERE id=? AND day=?', (item_id, today())).fetchone()
    if not item or item['status'] != 'pending':
        abort(400, '这项安排已经处理，请刷新。')
    db.execute("UPDATE items SET status='skipped' WHERE id=?", (item_id,))


@bp.post('/plan/order')
@mutation
def order(db, data):
    ids = data.get('ids')
    actual = [r[0] for r in db.execute('SELECT id FROM items WHERE day=?', (today(),))]
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or len(ids) != len(actual) or set(ids) != set(actual):
        abort(400, '排序列表无效。')
    for pos, item_id in enumerate(ids):
        db.execute('UPDATE items SET position=? WHERE id=?', (pos, item_id))


@bp.post('/settings')
@mutation
def settings(db, data):
    minutes = integer(data.get('default_minutes'), '默认可用分钟', 0, 960)
    weekly, overrides = read_capacity(db)
    try:
        weekly, overrides = validate_capacity(data.get('weekly_minutes', weekly),
                                              data.get('date_overrides', overrides))
    except ValueError as error:
        abort(400, str(error))
    set_value(db, 'default_minutes', minutes)
    set_value(db, 'weekly_minutes', json.dumps(weekly, ensure_ascii=False))
    set_value(db, 'date_overrides', json.dumps(overrides, ensure_ascii=False, sort_keys=True))


@bp.post('/password')
@mutation
def password(db, data):
    old, new = data.get('old_password'), data.get('new_password')
    if not isinstance(old, str) or len(old) > 256 or not check_password_hash(value(db, 'password_hash'), old):
        abort(400, '当前密码不正确。')
    if not isinstance(new, str) or not 12 <= len(new) <= 256:
        abort(400, '新密码须为 12–256 个字符。')
    set_value(db, 'password_hash', generate_password_hash(new))
    version = str(int(value(db, 'auth_version')) + 1)
    set_value(db, 'auth_version', version)
    session['auth_version'] = version


@bp.get('/export')
def export():
    require_auth()
    from .backup import export_data
    db = get_db()
    db.execute('BEGIN')
    try:
        data = export_data(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    response = jsonify(data)
    response.headers['Content-Disposition'] = f'attachment; filename="day-enough-{today()}.json"'
    return response


@bp.post('/restore')
@mutation
def restore(db, data):
    if data.get('confirmation') != '恢复':
        abort(400, '请输入「恢复」以确认替换现有任务数据。')
    from .backup import restore_data
    try:
        restore_data(db, data.get('backup'))
    except (ValueError, sqlite3.Error, TypeError, KeyError) as exc:
        abort(400, f'备份格式无效，未修改现有数据：{exc}')
