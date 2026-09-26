from copy import deepcopy

from day_enough.db import get_db
from test_recurrence import add_rule


def create_stage(browser, **changes):
    response = browser.post('/stages', {'title': '这个周末', 'start_date': '2026-09-14',
        'end_date': '2026-09-15', 'description': '完成课程任务', **changes})
    assert response.status_code == 200, response.json
    return response.json['stages'][0]


def save_target(browser, stage, task, mode='complete', minutes=0):
    return browser.post(f"/stages/{stage['id']}/targets", {'version': stage['version'],
        'task_id': task['id'], 'mode': mode, 'target_minutes': minutes})


def test_stage_progress_and_overdue_carry_without_changing_daily_plan(browser, app):
    first = browser.add(title='课程报告', remaining_minutes=40)
    second = browser.add(title='读书', remaining_minutes=50)
    stage = create_stage(browser)
    assert save_target(browser, stage, first).status_code == 200
    stage = browser.state()['stages'][0]
    assert save_target(browser, stage, second, 'minutes', 30).status_code == 200
    assert browser.state()['plan'] is None
    assert browser.post(f"/tasks/{second['id']}/work", {'minutes': 12}).status_code == 200
    stage = browser.state()['stages'][0]
    target = next(t for t in stage['targets'] if t['task_id'] == second['id'])
    assert target['progress_minutes'] == 12 and not target['completed']
    with app.app_context():
        app.config['TODAY'] = '2026-09-16'
    state = browser.state()
    assert state['plan'] is None and state['stages'][0]['overdue_count'] == 2
    closed = browser.post(f"/stages/{stage['id']}/status", {'version': state['stages'][0]['version'], 'status': 'closed'})
    assert closed.status_code == 200 and closed.json['stages'][0]['overdue_count'] == 0
    reopened = browser.post(f"/stages/{stage['id']}/status", {'version': closed.json['stages'][0]['version'], 'status': 'active'})
    assert reopened.status_code == 200 and reopened.json['stages'][0]['overdue_count'] == 2
    assert browser.post(f"/tasks/{second['id']}/work", {'minutes': 18}).status_code == 200
    assert browser.post(f"/tasks/{first['id']}/work", {'minutes': 40}).status_code == 200
    stage = browser.state()['stages'][0]
    assert stage['completed_count'] == 2 and stage['overdue_count'] == 0
    assert next(t for t in stage['targets'] if t['task_id'] == second['id'])['progress_minutes'] == 30
    assert browser.state()['plan'] is None


def test_stage_edit_targets_new_task_and_delete_keep_original_tasks(browser, app):
    task = browser.add()
    stage = create_stage(browser)
    wrong = browser.post(f"/stages/{stage['id']}", {'version': stage['version'],
        'title': '坏日期', 'start_date': '2026-09-16', 'end_date': '2026-09-15', 'description': ''})
    assert wrong.status_code == 400
    assert save_target(browser, stage, task, 'minutes', 90).status_code == 200
    assert save_target(browser, stage, task).status_code == 409
    stage = browser.state()['stages'][0]
    assert save_target(browser, stage, task, 'minutes', 60).status_code == 200
    stage = browser.state()['stages'][0]
    assert len(stage['targets']) == 1 and stage['targets'][0]['target_minutes'] == 60
    response = browser.post('/tasks', {'title': '新任务', 'remaining_minutes': 25, 'energy': 'medium',
        'consequence': 'medium', 'due_date': '', 'next_step': '',
        'stage_id': stage['id'], 'stage_version': stage['version']})
    assert response.status_code == 200, response.json
    stage = response.json['stages'][0]
    assert len(stage['targets']) == 2
    new_task = next(t for t in response.json['tasks'] if t['title'] == '新任务')
    assert browser.post(f"/stages/{stage['id']}/targets/{new_task['id']}/remove", {'version': stage['version']}).status_code == 200
    stage = browser.state()['stages'][0]
    assert browser.post(f"/stages/{stage['id']}/delete", {'version': stage['version'], 'confirmation': '删除'}).status_code == 200
    state = browser.state()
    assert state['stages'] == [] and {t['id'] for t in state['tasks']} == {task['id'], new_task['id']}
    with app.app_context():
        assert list(get_db().execute('PRAGMA foreign_key_check')) == []


def test_stage_restore_and_old_backup_compatibility(browser):
    task = browser.add()
    stage = create_stage(browser)
    assert save_target(browser, stage, task).status_code == 200
    exported = browser.client.get('/api/export').json
    assert exported['version'] == 6
    assert len(exported['tables']['stage_targets']) == 1
    bad = deepcopy(exported)
    bad['tables']['stages'][0]['end_date'] = '2026-09-13'
    assert browser.post('/restore', {'backup': bad, 'confirmation': '恢复'}).status_code == 400
    assert browser.client.get('/api/export').json == exported
    assert browser.post('/restore', {'backup': exported, 'confirmation': '恢复'}).status_code == 200
    assert browser.state()['stages'][0]['targets'][0]['task_id'] == task['id']
    old = deepcopy(exported)
    old['version'] = 5
    del old['tables']['stages']
    del old['tables']['stage_targets']
    assert browser.post('/restore', {'backup': old, 'confirmation': '恢复'}).status_code == 200
    assert browser.state()['stages'] == []


def test_stage_rejects_skip_policy_occurrence_and_cleans_deleted_tasks(browser):
    rule = add_rule(browser, frequency='daily')
    task = next(t for t in browser.state()['tasks'] if t['recurrence_id'] == rule['id'])
    stage = create_stage(browser)
    assert save_target(browser, stage, task).status_code == 400
    ordinary = browser.add()
    assert save_target(browser, stage, ordinary).status_code == 200
    state = browser.post(f"/tasks/{ordinary['id']}/delete", {'version': ordinary['version'], 'confirmation': '删除'})
    assert state.status_code == 200
    assert state.json['stages'][0]['targets'] == []


def test_deleting_recurrence_cleans_stage_target(browser, app):
    rule = add_rule(browser, frequency='weekly', weekdays=[0], missed_policy='carry')
    task = next(t for t in browser.state()['tasks'] if t['recurrence_id'] == rule['id'])
    stage = create_stage(browser)
    assert save_target(browser, stage, task).status_code == 200
    result = browser.post(f"/recurrences/{rule['id']}/delete", {'version': rule['version'], 'confirmation': '删除'})
    assert result.status_code == 200
    assert result.json['stages'][0]['targets'] == []
    with app.app_context():
        assert list(get_db().execute('PRAGMA foreign_key_check')) == []
