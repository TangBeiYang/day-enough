"""Deleting tasks must keep SQLite references valid and respect recurrence suppression."""
from day_enough.db import get_db
from test_recurrence import add_rule


def test_delete_ordinary_task_removes_plan_and_work_atomically(browser, app):
    task = browser.add()
    browser.post('/plan', {'budget': 120, 'energy': 'high'})
    browser.post('/tasks/' + task['id'] + '/work', {'minutes': 10})
    current = next(t for t in browser.state()['tasks'] if t['id'] == task['id'])
    assert browser.post('/tasks/' + task['id'] + '/delete', {'version': current['version']}).status_code == 400
    assert browser.post('/tasks/' + task['id'] + '/delete', {'version': task['version'], 'confirmation': '删除'}).status_code == 409
    state = browser.post('/tasks/' + task['id'] + '/delete', {'version': current['version'], 'confirmation': '删除'}).json
    assert state['tasks'] == [] and state['items'] == [] and state['worked_minutes'] == 0
    assert state['plan']['budget'] == 120
    with app.app_context():
        db = get_db()
        assert db.execute('SELECT COUNT(*) FROM work_logs').fetchone()[0] == 0
        assert list(db.execute('PRAGMA foreign_key_check')) == []


def test_delete_one_occurrence_is_not_regenerated_and_roundtrips(browser, app):
    rule = add_rule(browser, frequency='weekly', weekdays=[0, 2])
    first = next(t for t in browser.state()['tasks'] if t['occurrence_date'] == '2026-09-14')
    second = next(t for t in browser.state()['tasks'] if t['occurrence_date'] == '2026-09-16')
    browser.post('/plan', {'budget': 120, 'energy': 'high'})
    browser.post('/tasks/' + first['id'] + '/work', {'minutes': 5})
    first = next(t for t in browser.state()['tasks'] if t['id'] == first['id'])
    result = browser.post('/tasks/' + first['id'] + '/delete', {'version': first['version'], 'confirmation': '删除'})
    assert result.status_code == 200
    assert {t['id'] for t in result.json['tasks']} == {second['id']}
    assert result.json['recurrences'][0]['id'] == rule['id']
    assert browser.state()['tasks'] == result.json['tasks']
    backup = browser.client.get('/api/export').json
    assert backup['tables']['suppressed_occurrences'] == [{'recurrence_id': rule['id'], 'occurrence_date': '2026-09-14'}]
    assert browser.post('/restore', {'backup': backup, 'confirmation': '恢复'}).status_code == 200
    assert {t['id'] for t in browser.state()['tasks']} == {second['id']}
    with app.app_context():
        assert list(get_db().execute('PRAGMA foreign_key_check')) == []


def test_delete_rule_removes_all_instances_and_suppression(browser, app):
    rule = add_rule(browser, frequency='weekly', weekdays=[0, 2])
    first = browser.state()['tasks'][0]
    browser.post('/tasks/' + first['id'] + '/delete', {'version': first['version'], 'confirmation': '删除'})
    state = browser.state()
    assert browser.post('/recurrences/' + rule['id'] + '/delete', {'version': rule['version'], 'confirmation': 'wrong'}).status_code == 400
    result = browser.post('/recurrences/' + rule['id'] + '/delete', {'version': rule['version'], 'confirmation': '删除'})
    assert result.status_code == 200
    assert result.json['tasks'] == [] and result.json['recurrences'] == []
    assert browser.client.get('/api/export').json['tables']['suppressed_occurrences'] == []
    with app.app_context():
        assert list(get_db().execute('PRAGMA foreign_key_check')) == []


def test_v4_backup_restores_without_suppression_table(browser):
    add_rule(browser)
    backup = browser.client.get('/api/export').json
    backup['version'] = 4
    del backup['tables']['suppressed_occurrences']
    result = browser.post('/restore', {'backup': backup, 'confirmation': '恢复'})
    assert result.status_code == 200
    assert result.json['recurrences'] and result.json['tasks']
    assert browser.client.get('/api/export').json['tables']['suppressed_occurrences'] == []
