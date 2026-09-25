def test_manual_plan_allows_over_budget_and_keeps_order(browser):
    first = browser.add(title='写报告', remaining_minutes=90)
    second = browser.add(title='背单词', remaining_minutes=30, energy='high')
    response = browser.post('/plan/manual', {'budget': 20, 'energy': 'low', 'items': [
        {'task_id': second['id'], 'minutes': 25}, {'task_id': first['id'], 'minutes': 40}]})
    assert response.status_code == 200, response.json
    state = response.json
    assert [(item['task_id'], item['planned_minutes']) for item in state['items']] == [
        (second['id'], 25), (first['id'], 40)]
    assert state['remaining_planned'] == 65
    assert any('超过今日预算 45 分钟' in warning for warning in state['warnings'])


def test_manual_edit_preserves_work_and_handled_shares(browser):
    first = browser.add(title='写报告', remaining_minutes=90)
    second = browser.add(title='背单词', remaining_minutes=30)
    third = browser.add(title='复习', remaining_minutes=50)
    initial = browser.post('/plan/manual', {'budget': 90, 'energy': 'medium', 'items': [
        {'task_id': first['id'], 'minutes': 40}, {'task_id': second['id'], 'minutes': 20},
        {'task_id': third['id'], 'minutes': 20}]})
    assert initial.status_code == 200
    logged = browser.post(f"/tasks/{first['id']}/work", {'minutes': 10})
    assert logged.status_code == 200
    skipped = browser.post('/items/' + next(i['id'] for i in logged.json['items'] if i['task_id'] == second['id']) + '/skip')
    assert skipped.status_code == 200
    edited = browser.post('/plan/manual', {'budget': 15, 'energy': 'high', 'items': [
        {'task_id': third['id'], 'minutes': 25}, {'task_id': first['id'], 'minutes': 15}]})
    assert edited.status_code == 200, edited.json
    items = edited.json['items']
    assert [i['task_id'] for i in items] == [third['id'], first['id'], second['id']]
    assert [(i['status'], i['planned_minutes'], i['done_minutes']) for i in items] == [
        ('pending', 25, 0), ('pending', 25, 10), ('skipped', 20, 0)]
    assert edited.json['worked_minutes'] == 10
    assert edited.json['remaining_planned'] == 40
    cleared = browser.post('/plan/manual', {'budget': 15, 'energy': 'high', 'items': []})
    assert cleared.status_code == 200, cleared.json
    assert [(i['task_id'], i['status'], i['done_minutes']) for i in cleared.json['items']] == [
        (first['id'], 'done', 10), (second['id'], 'skipped', 0)]
    assert cleared.json['worked_minutes'] == 10


def test_manual_plan_rejects_invalid_choices_atomically(browser):
    task = browser.add(remaining_minutes=20)
    before = browser.state()
    choices = [
        [{'task_id': task['id'], 'minutes': 21}],
        [{'task_id': task['id'], 'minutes': 10}, {'task_id': task['id'], 'minutes': 5}],
        [{'task_id': task['id'], 'minutes': 0}],
    ]
    for items in choices:
        response = browser.post('/plan/manual', {'budget': 5, 'energy': 'medium', 'items': items})
        assert response.status_code == 400
        after = browser.state()
        assert after['revision'] == before['revision']
        assert after['plan'] is None
        assert after['items'] == []
