import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from day_enough.db import connect, init_db
from day_enough.recurrence import next_occurrence
from conftest import Browser


def rule_payload(**overrides):
    return {'title': '每天背单词', 'remaining_minutes': 20, 'energy': 'medium',
            'consequence': 'medium', 'next_step': '复习新词', 'planned_date': '2026-09-14',
            'frequency': 'daily', 'weekdays': [], 'month_day': 0,
            'missed_policy': 'skip', 'due_on_planned': False, **overrides}


def add_rule(browser, **overrides):
    response = browser.post('/recurrences', rule_payload(**overrides))
    assert response.status_code == 200, response.json
    return next(r for r in response.json['recurrences'] if r['title'] == overrides.get('title', '每天背单词'))


@pytest.mark.parametrize('frequency,weekdays,month_day,start,after,expected', [
    ('daily', [], 0, '2026-09-14', '2026-09-15', '2026-09-15'),
    ('daily', [], 0, '2026-10-01', '2026-09-15', '2026-10-01'),
    ('weekly', [0, 2, 4], 0, '2026-09-14', '2026-09-15', '2026-09-16'),
    ('weekly', [0, 2, 4], 0, '2026-09-14', '2026-09-19', '2026-09-21'),
    ('monthly', [], 31, '2026-01-01', '2026-02-01', '2026-02-28'),
    ('monthly', [], 31, '2028-01-01', '2028-02-01', '2028-02-29'),
    ('monthly', [], 31, '2026-01-01', '2026-03-01', '2026-03-31'),
    ('monthly', [], 0, '2026-01-01', '2026-04-01', '2026-04-30'),
    ('monthly', [], 5, '2026-09-14', '2026-09-14', '2026-10-05'),
    ('monthly', [], 31, '2026-12-31', '2027-01-01', '2027-01-31'),
])
def test_calendar(frequency, weekdays, month_day, start, after, expected):
    assert next_occurrence(frequency, weekdays, month_day, start, after) == expected


def test_ordinary_planned_date_gates_recommendation_and_can_be_cleared(browser, app):
    task = browser.add(planned_date='2026-09-16')
    assert browser.post('/plan', {'budget': 120, 'energy': 'high'}).json['items'] == []
    app.config['TODAY'] = '2026-09-16'
    state = browser.state()
    assert state['unplanned_scheduled'] == [task['id']]
    plan = browser.post('/plan', {'budget': 120, 'energy': 'high'}).json
    assert plan['items'][0]['planned_date'] == '2026-09-16'
    response = browser.post('/tasks/' + task['id'], {**task, 'planned_date': '2026-09-17'})
    assert response.status_code == 200
    assert response.json['items'][0]['status'] == 'skipped'
    updated = response.json['tasks'][0]
    response = browser.post('/tasks/' + task['id'], {**updated, 'planned_date': ''})
    assert response.json['tasks'][0]['planned_date'] == ''
    assert browser.post('/tasks/' + task['id'], {**response.json['tasks'][0], 'planned_date': '2026-09-18'}).status_code == 400


def test_daily_missed_partial_is_preserved_without_debt(browser, app):
    rule = add_rule(browser)
    first = browser.state()['tasks'][0]
    assert first['planned_date'] == '2026-09-14' and first['due_date'] == ''
    plan = browser.post('/plan', {'budget': 120, 'energy': 'medium'}).json
    assert plan['items'][0]['planned_minutes'] == 20
    browser.post('/tasks/' + first['id'] + '/work', {'minutes': 10})
    app.config['TODAY'] = '2026-09-16'
    state = browser.state()
    tasks = {t['occurrence_date']: t for t in state['tasks']}
    assert len(tasks) == 3
    assert tasks['2026-09-14']['status'] == 'archived'
    assert tasks['2026-09-14']['missed'] == 1
    assert tasks['2026-09-14']['worked_minutes'] == 10
    assert tasks['2026-09-14']['remaining_minutes'] == 10
    assert tasks['2026-09-15']['missed'] == 1
    assert tasks['2026-09-16']['remaining_minutes'] == 20
    assert state['recurrences'][0]['id'] == rule['id']
    plan = browser.post('/plan', {'budget': 120, 'energy': 'medium'}).json
    assert [i['task_id'] for i in plan['items']] == [tasks['2026-09-16']['id']]


def test_carry_occurrences_are_independent_and_completion_does_not_stop_rule(browser, app):
    add_rule(browser, missed_policy='carry', due_on_planned=True)
    first = browser.state()['tasks'][0]
    app.config['TODAY'] = '2026-09-15'
    state = browser.state()
    assert len(state['tasks']) == 2
    assert all(t['status'] == 'active' for t in state['tasks'])
    assert all(t['due_date'] == t['occurrence_date'] for t in state['tasks'])
    response = browser.post('/tasks/' + first['id'], {**first, 'status': 'done'})
    assert response.status_code == 200
    assert len([t for t in response.json['tasks'] if t['status'] == 'active']) == 1
    assert response.json['recurrences'][0]['status'] == 'active'
    assert any('已过截止日期' in warning for warning in state['warnings'])


def test_pause_resume_skips_paused_dates_and_keeps_existing_work(browser, app):
    rule = add_rule(browser, missed_policy='carry')
    result = browser.post('/recurrences/' + rule['id'] + '/status', {'version': rule['version'], 'status': 'paused'})
    assert result.status_code == 200
    app.config['TODAY'] = '2026-09-18'
    state = browser.state()
    assert len(state['tasks']) == 1 and state['tasks'][0]['status'] == 'active'
    result = browser.post('/recurrences/' + rule['id'] + '/status', {'version': state['recurrences'][0]['version'], 'status': 'active'})
    assert {t['occurrence_date'] for t in result.json['tasks']} == {'2026-09-14', '2026-09-18'}


def test_edit_rule_preserves_generated_instances_and_current_plan(browser, app):
    rule = add_rule(browser, missed_policy='carry')
    original = browser.state()['tasks'][0]
    plan = browser.post('/plan', {'budget': 120, 'energy': 'medium'}).json
    response = browser.post('/recurrences/' + rule['id'], rule_payload(
        version=rule['version'], remaining_minutes=40, title='复习英语', missed_policy='skip'))
    assert response.status_code == 200, response.json
    assert response.json['tasks'][0] == original
    assert response.json['items'] == plan['items']
    app.config['TODAY'] = '2026-09-15'
    tasks = browser.state()['tasks']
    old = next(t for t in tasks if t['id'] == original['id'])
    new = next(t for t in tasks if t['id'] != original['id'])
    assert old['status'] == 'active' and old['title'] == '每天背单词'
    assert new['title'] == '复习英语' and new['remaining_minutes'] == 40


def test_edit_one_occurrence_leaves_rule_and_future_occurrences_unchanged(browser, app):
    add_rule(browser, missed_policy='carry')
    task = browser.state()['tasks'][0]
    result = browser.post('/tasks/' + task['id'], {**task, 'title': '今天只复习旧词', 'planned_date': '2026-09-16', 'remaining_minutes': 10})
    assert result.status_code == 200
    assert result.json['recurrences'][0]['title'] == '每天背单词'
    app.config['TODAY'] = '2026-09-15'
    state = browser.state()
    assert next(t for t in state['tasks'] if t['occurrence_date'] == '2026-09-15')['remaining_minutes'] == 20


def test_repeated_and_concurrent_reads_do_not_duplicate_occurrences(browser, app):
    add_rule(browser)
    before = browser.state()
    assert browser.state()['revision'] == before['revision']
    a, b = Browser(app), Browser(app)
    app.config['TODAY'] = '2026-09-15'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda client: client.state(), [a, b]))
    assert results[0]['revision'] == results[1]['revision'] == before['revision'] + 1
    assert len(results[0]['tasks']) == len(results[1]['tasks']) == 2
    assert {t['id'] for t in results[0]['tasks']} == {t['id'] for t in results[1]['tasks']}


def test_weekly_multiple_days_and_monthly_short_month(browser, app):
    rule = add_rule(browser, frequency='weekly', weekdays=[0, 2, 4])
    app.config['TODAY'] = '2026-09-20'
    assert {t['occurrence_date'] for t in browser.state()['tasks']} == {'2026-09-14', '2026-09-16', '2026-09-18'}
    app.config['TODAY'] = '2027-01-30'
    # Pause weekly generation before advancing several months.
    browser.post('/recurrences/' + rule['id'] + '/status', {'version': rule['version'], 'status': 'paused'})
    monthly = add_rule(browser, title='月末总结', frequency='monthly', month_day=31, planned_date='2027-01-30')
    assert monthly['next_date'] == '2027-01-31'
    app.config['TODAY'] = '2027-03-31'
    dates = {t['occurrence_date'] for t in browser.state()['tasks'] if t['recurrence_id'] == monthly['id']}
    assert dates == {'2027-01-31', '2027-02-28', '2027-03-31'}


def test_new_rule_does_not_refill_existing_plan_and_reports_unplanned(browser):
    original = browser.post('/plan', {'budget': 0, 'energy': 'low'}).json
    add_rule(browser, energy='high')
    state = browser.state()
    assert state['items'] == original['items'] == []
    assert len(state['unplanned_scheduled']) == 1
    state = browser.post('/plan', {'budget': 40, 'energy': 'low'}).json
    assert state['items'][0]['planned_minutes'] == 10
    assert state['remaining_planned'] == 10


@pytest.mark.parametrize('fields', [
    {'frequency': 'yearly'}, {'frequency': 'weekly', 'weekdays': []},
    {'frequency': 'weekly', 'weekdays': [True]}, {'weekdays': [7]},
    {'month_day': 32}, {'planned_date': ''}, {'planned_date': '2026-02-30'},
    {'planned_date': '2026-09-13'}, {'remaining_minutes': 0},
    {'missed_policy': 'whatever'}, {'due_on_planned': 2},
])
def test_invalid_rule_does_not_write_data(browser, fields):
    result = browser.post('/recurrences', rule_payload(**fields))
    assert result.status_code == 400
    assert browser.state()['recurrences'] == [] and browser.state()['tasks'] == []


def test_backup_v2_roundtrip_and_invalid_rules(browser):
    add_rule(browser, frequency='weekly', weekdays=[0, 2])
    task = browser.state()['tasks'][0]
    browser.post('/tasks/' + task['id'] + '/work', {'minutes': 5})
    backup = browser.client.get('/api/export').json
    assert backup['version'] == 2
    response = browser.post('/restore', {'backup': backup, 'confirmation': '恢复'})
    assert response.status_code == 200, response.json
    assert browser.client.get('/api/export').json == backup
    bad = copy.deepcopy(backup)
    bad['tables']['recurrences'][0]['weekdays'] = '[]'
    assert browser.post('/restore', {'backup': bad, 'confirmation': '恢复'}).status_code == 400
    assert browser.client.get('/api/export').json == backup
    bad = copy.deepcopy(backup)
    bad['tables']['tasks'].append({**bad['tables']['tasks'][0], 'id': str(uuid4())})
    assert browser.post('/restore', {'backup': bad, 'confirmation': '恢复'}).status_code == 400


def test_old_json_backup_restores_with_empty_schedule(browser):
    task = browser.add()
    backup = browser.client.get('/api/export').json
    backup['version'] = 1
    del backup['tables']['recurrences']
    for row in backup['tables']['tasks']:
        for key in ('planned_date', 'recurrence_id', 'occurrence_date', 'missed_policy', 'missed'):
            del row[key]
    add_rule(browser)
    response = browser.post('/restore', {'backup': backup, 'confirmation': '恢复'})
    assert response.status_code == 200, response.json
    assert response.json['recurrences'] == []
    assert response.json['tasks'][0]['id'] == task['id']
    assert response.json['tasks'][0]['planned_date'] == ''


def test_existing_database_migration_preserves_references_and_is_repeatable(tmp_path):
    db = connect(str(tmp_path / 'legacy.sqlite'))
    try:
        db.executescript(Path(__file__).with_name('fixtures').joinpath('schema_v1.sql').read_text())
        db.execute("INSERT INTO tasks VALUES ('task','原任务','2026-09-20','high','medium',60,10,'','active',3,'stamp','stamp')")
        db.execute("INSERT INTO plans VALUES ('2026-09-14',120,'medium','stamp')")
        db.execute("INSERT INTO items VALUES ('item','2026-09-14','task',30,10,'pending','原理由',0)")
        db.execute("INSERT INTO work_logs VALUES ('log','task','2026-09-14',10,'medium','stamp')")
        db.execute("UPDATE meta SET value='17' WHERE key='revision'")
        init_db(db)
        init_db(db)
        task = dict(db.execute('SELECT * FROM tasks').fetchone())
        assert task['worked_minutes'] == 10 and task['version'] == 3
        assert task['planned_date'] == '' and task['recurrence_id'] is None
        assert db.execute('SELECT task_id FROM items').fetchone()[0] == 'task'
        assert db.execute('SELECT minutes FROM work_logs').fetchone()[0] == 10
        assert db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0] == '17'
        assert list(db.execute('PRAGMA foreign_key_check')) == []
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2
    finally:
        db.close()
