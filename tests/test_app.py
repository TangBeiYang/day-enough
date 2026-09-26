import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from uuid import uuid4
import pytest
from day_enough import create_app
from day_enough.db import get_db, value
from day_enough.planner import recommend
from conftest import Browser, PASSWORD


def test_private_data_and_csrf(app, browser):
    anonymous = app.test_client()
    assert anonymous.get('/api/state').status_code == 401
    assert anonymous.get('/api/export').status_code == 401
    assert browser.client.post('/api/tasks', json={}).status_code == 403
    page = anonymous.get('/')
    assert 'default-src' in page.headers['Content-Security-Policy']
    assert page.headers['Cache-Control'] == 'no-store'
    assert b'DayEnough' in page.data


def test_login_limit_and_password_reset(app, browser):
    other = Browser(app)
    bad = app.test_client()
    csrf = bad.get('/api/session').json['csrf']
    # Two successful logins already consumed attempts in this window.
    for _ in range(8):
        assert bad.post('/api/login', json={'username': 'owner', 'password': 'wrong'}, headers={'X-CSRF-Token': csrf}).status_code == 401
    assert bad.post('/api/login', json={'username': 'owner', 'password': 'wrong'}, headers={'X-CSRF-Token': csrf}).status_code == 429
    assert browser.post('/password', {'old_password':PASSWORD, 'new_password':'new-password-123456'}).status_code == 200
    assert other.client.get('/api/state').status_code == 401
    assert browser.client.get('/api/state').status_code == 200


def test_task_validation_and_completion(browser):
    task = browser.add()
    assert browser.post('/tasks', {'title': '', 'due_date':'invalid'}).status_code == 400
    assert browser.post('/tasks', {**task, 'remaining_minutes':True}).status_code == 400
    assert browser.post('/tasks', {**task, 'due_date':'2026-02-30'}).status_code == 400
    response = browser.post('/tasks/' + task['id'], {**task, 'status':'done'})
    assert response.status_code == 200
    task = response.json['tasks'][0]
    assert task['remaining_minutes'] == 0 and task['worked_minutes'] == 0
    response = browser.post('/tasks/' + task['id'], {**task, 'status':'active', 'remaining_minutes':60})
    assert response.json['tasks'][0]['status'] == 'active'


def test_task_without_deadline_is_planned_without_deadline_warning(browser):
    undated = browser.add(title='长期阅读', due_date='', remaining_minutes=90)
    dated = browser.add(title='明天交的作业', due_date='2026-09-15', remaining_minutes=30)
    result = browser.post('/plan', {'budget': 90, 'energy': 'high'}).json
    assert [item['task_id'] for item in result['items']] == [dated['id'], undated['id']]
    undated_item = next(item for item in result['items'] if item['task_id'] == undated['id'])
    assert undated_item['planned_minutes'] == 30
    assert '无截止日期' in undated_item['reason']
    assert all('长期阅读' not in warning for warning in result['warnings'])

    exported = browser.client.get('/api/export').json
    assert next(task for task in exported['tables']['tasks'] if task['id'] == undated['id'])['due_date'] == ''
    restored = browser.post('/restore', {'backup': exported, 'confirmation': '恢复'})
    assert restored.status_code == 200
    assert next(task for task in restored.json['tasks'] if task['id'] == undated['id'])['due_date'] == ''


def test_plan_is_persistent_no_automatic_refill(browser, app):
    task = browser.add(remaining_minutes=180)
    plan = browser.post('/plan', {'budget':120, 'energy':'medium'}).json
    item = plan['items'][0]
    assert item['planned_minutes'] == 45
    result = browser.post('/tasks/' + task['id'] + '/work', {'minutes':45}).json
    assert result['tasks'][0]['remaining_minutes'] == 135
    assert result['items'][0]['status'] == 'done'
    assert result['remaining_planned'] == 0
    # Opening from another computer and restarting app both preserve the plan.
    assert Browser(app).state()['items'] == result['items']
    restarted = create_app({**app.config, 'TESTING':True})
    assert Browser(restarted).state()['items'] == result['items']
    assert browser.post('/plan', {'budget':120, 'energy':'medium'}).json['remaining_planned'] == 0


def test_two_tabs_and_idempotent_work(browser, app):
    task = browser.add()
    other = Browser(app)
    old = other.state()
    key = str(uuid4())
    first = browser.post('/tasks/' + task['id'] + '/work', {'minutes':20}, base=old, key=key)
    assert first.status_code == 200
    replay = browser.post('/tasks/' + task['id'] + '/work', {'minutes':20}, base=old, key=key)
    assert replay.status_code == 200 and replay.json['worked_minutes'] == 20
    conflict = other.post('/tasks/' + task['id'], {**task, 'title':'旧页面内容'}, base=old)
    assert conflict.status_code == 409
    assert browser.state()['tasks'][0]['title'] == '课程报告'
    assert browser.post('/tasks/' + task['id'] + '/work', {'minutes':21}, base=old, key=key).status_code == 409


def test_simultaneous_writes_are_serialized(browser, app):
    task = browser.add()
    a, b = Browser(app), Browser(app)
    base = browser.state()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda client: client.post('/tasks/' + task['id'] + '/work', {'minutes':10}, base=base).status_code, [a,b]))
    assert sorted(results) == [200,409]
    assert browser.state()['worked_minutes'] == 10


def test_midnight_rejects_old_write_and_new_plan(browser, app):
    task = browser.add()
    old = browser.post('/plan', {'budget':120, 'energy':'medium'}).json
    app.config['TODAY'] = '2026-09-15'
    assert browser.post('/tasks/' + task['id'] + '/work', {'minutes':10}, base=old).status_code == 409
    fresh = browser.state()
    assert fresh['plan'] is None and fresh['items'] == [] and fresh['worked_minutes'] == 0
    assert len(browser.post('/plan', {'budget':120,'energy':'medium'}).json['items']) == 1


def test_partial_replan_budget_skip_and_high_energy(browser):
    task = browser.add(energy='high', due_date='2026-09-14', remaining_minutes=300)
    second = browser.add(title='邮件', energy='low', remaining_minutes=80)
    plan = browser.post('/plan', {'budget':120, 'energy':'low'}).json
    high = next(i for i in plan['items'] if i['task_id'] == task['id'])
    assert high['planned_minutes'] == 30
    browser.post('/tasks/' + task['id'] + '/work', {'minutes':10})
    new = browser.post('/plan', {'budget':120, 'energy':'low'}).json
    high = next(i for i in new['items'] if i['task_id'] == task['id'])
    assert high['planned_minutes'] - high['done_minutes'] == 20
    assert new['worked_minutes'] + new['remaining_planned'] <= 120
    browser.post('/items/' + high['id'] + '/skip')
    final = browser.post('/plan', {'budget':120, 'energy':'high'}).json
    assert next(i for i in final['items'] if i['task_id'] == task['id'])['status'] == 'skipped'


def test_zero_budget_overrun_and_archive(browser):
    task = browser.add(remaining_minutes=10)
    assert browser.post('/plan', {'budget':0,'energy':'low'}).json['items'] == []
    work = browser.post('/tasks/' + task['id'] + '/work', {'minutes':20}).json
    assert work['tasks'][0]['remaining_minutes'] == 0
    assert work['tasks'][0]['worked_minutes'] == 20
    assert work['warnings']
    task = browser.add(title='暂不推进')
    result = browser.post('/tasks/' + task['id'], {**task, 'status':'archived'})
    assert result.status_code == 200
    assert browser.post('/plan', {'budget':120,'energy':'high'}).json['items'] == []


def test_order_persists(browser):
    browser.add(title='甲')
    browser.add(title='乙')
    items = browser.post('/plan', {'budget':120,'energy':'high'}).json['items']
    ids = [i['id'] for i in reversed(items)]
    assert len(ids) == 2
    result = browser.post('/plan/order', {'ids':ids})
    assert [i['id'] for i in result.json['items']] == ids
    assert browser.post('/plan/order', {'ids':[ids[0],ids[0]]}).status_code == 400


def test_backup_restore_roundtrip_and_rollback(browser, app, tmp_path):
    task = browser.add()
    browser.post('/plan', {'budget':100,'energy':'medium'})
    browser.post('/tasks/' + task['id'] + '/work', {'minutes':15})
    exported = browser.client.get('/api/export').json
    assert 'password' not in str(exported)
    browser.add(title='备份后的任务')
    result = browser.post('/restore', {'backup':exported,'confirmation':'恢复'})
    assert result.status_code == 200, result.json
    assert len(result.json['tasks']) == 1
    assert browser.client.get('/api/export').json == exported
    bad = copy.deepcopy(exported)
    bad['tables']['items'][0]['task_id'] = str(uuid4())
    assert browser.post('/restore', {'backup':bad,'confirmation':'恢复'}).status_code == 400
    assert browser.client.get('/api/export').json == exported
    # Online SQLite copy includes a valid database, without copying a live WAL file.
    backup = tmp_path / 'snapshot.sqlite'
    command = app.test_cli_runner().invoke(args=['backup',str(backup)])
    assert command.exit_code == 0, command.output
    with sqlite3.connect(backup) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 1
    restored_app = create_app({'TESTING':True,'DATABASE':str(backup),'SECRET_KEY':'different-server','TODAY':'2026-09-14'})
    assert Browser(restored_app).client.get('/api/export').json == exported


@pytest.mark.parametrize('energy', ['low','medium','high'])
@pytest.mark.parametrize('budget', [0,1,30,120,960])
def test_allocation_respects_time_and_energy(energy, budget):
    day=date(2026,9,14)
    tasks=[{'id':str(i),'title':str(i),'due_date':(day+timedelta(days=i%5)).isoformat(),
            'energy':['low','medium','high'][i%3], 'consequence':'high', 'status':'active',
            'remaining_minutes':50+i*20} for i in range(20)]
    picks=recommend(tasks,day,budget,energy)
    assert sum(p['planned_minutes'] for p in picks)<=budget
    high_total=sum(p['planned_minutes'] for p in picks if tasks[int(p['task_id'])]['energy']=='high')
    assert high_total<=int(budget*{'low':.25,'medium':.6,'high':1}[energy])
    assert all(0<p['planned_minutes']<=tasks[int(p['task_id'])]['remaining_minutes'] for p in picks)


def test_backup_rejects_non_uuid_identifiers(browser):
    browser.add()
    data = browser.client.get('/api/export').json
    data['tables']['tasks'][0]['id'] = '" onclick="alert(1)'
    result = browser.post('/restore', {'backup':data,'confirmation':'恢复'})
    assert result.status_code == 400
    assert len(browser.state()['tasks']) == 1


def test_password_reset_during_login_does_not_authorize_old_password(app, monkeypatch):
    import day_enough.api as api
    from day_enough.db import set_value
    original = api.check_password_hash
    def concurrent_reset(stored, password):
        valid = original(stored,password)
        with app.app_context():
            set_value(get_db(),'auth_version',1)
        return valid
    monkeypatch.setattr(api,'check_password_hash',concurrent_reset)
    client = app.test_client()
    csrf = client.get('/api/session').json['csrf']
    client.post('/api/login',json={'username':'owner','password':PASSWORD},headers={'X-CSRF-Token':csrf})
    assert client.get('/api/state').status_code == 401
