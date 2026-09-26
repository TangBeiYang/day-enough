import sqlite3
import zipfile
from uuid import uuid4

from day_enough import create_app
from day_enough.db import get_db, set_value
from conftest import Browser, PASSWORD


def set_invite(app, code='invitation-12345'):
    result = app.test_cli_runner().invoke(args=['set-invite-code'], input=code + '\n' + code + '\n')
    assert result.exit_code == 0, result.output


def register(app, username='alice', password='alice-password-123', code='invitation-12345'):
    client = app.test_client()
    csrf = client.get('/api/session').json['csrf']
    response = client.post('/api/register', json={'username': username, 'password': password,
                            'invite_code': code}, headers={'X-CSRF-Token': csrf})
    return client, response


def add_task(client, title):
    state = client.get('/api/state').json
    response = client.post('/api/tasks', json={'title': title, 'due_date': '',
        'remaining_minutes': 30, 'energy': 'medium', 'consequence': 'medium',
        'next_step': '', 'revision': state['revision'], 'day': state['day']},
        headers={'X-CSRF-Token': client.get('/api/session').json['csrf'],
                 'Idempotency-Key': str(uuid4())})
    assert response.status_code == 200, response.json
    return next(t for t in response.json['tasks'] if t['title'] == title)


def test_invite_rotation_registration_and_username_uniqueness(app):
    anonymous = app.test_client()
    assert anonymous.post('/api/register', json={}).status_code == 403
    client, response = register(app)
    assert response.status_code == 503
    set_invite(app)
    client, response = register(app, code='wrong')
    assert response.status_code == 403
    client, response = register(app, username='Alice')
    assert response.status_code == 200
    assert client.get('/api/session').json['username'] == 'alice'
    _, response = register(app, username='ＡＬＩＣＥ')
    assert response.status_code == 409
    set_invite(app, 'new-invite-12345')
    _, response = register(app, username='bob')
    assert response.status_code == 403
    _, response = register(app, username='bob', code='new-invite-12345')
    assert response.status_code == 200
    assert app.test_cli_runner().invoke(args=['disable-registration']).exit_code == 0
    _, response = register(app, username='charlie', code='new-invite-12345')
    assert response.status_code == 503
    assert client.get('/api/state').status_code == 200


def test_bad_invites_are_rate_limited(app):
    set_invite(app)
    client = app.test_client()
    csrf = client.get('/api/session').json['csrf']
    payload = {'username':'guessed-user', 'password':'password-12345', 'invite_code':'incorrect-code'}
    for _ in range(10):
        assert client.post('/api/register', json=payload,
                           headers={'X-CSRF-Token':csrf}).status_code == 403
    assert client.post('/api/register', json=payload,
                       headers={'X-CSRF-Token':csrf}).status_code == 429


def test_accounts_isolate_tasks_settings_revisions_and_backups(app, browser):
    owner_task = browser.add(title='原来的任务')
    set_invite(app)
    alice, response = register(app)
    assert response.status_code == 200
    assert alice.get('/api/state').json['tasks'] == []
    alice_task = add_task(alice, 'Alice 的任务')
    assert [task['id'] for task in browser.state()['tasks']] == [owner_task['id']]
    assert [task['id'] for task in alice.get('/api/state').json['tasks']] == [alice_task['id']]
    assert browser.post('/tasks/' + alice_task['id'], {**alice_task, 'title':'越权'}).status_code == 404
    alice_state = alice.get('/api/state').json
    response = alice.post('/api/tasks/' + owner_task['id'], json={**owner_task,
        'revision': alice_state['revision'], 'day': alice_state['day']}, headers={
        'X-CSRF-Token': alice.get('/api/session').json['csrf'], 'Idempotency-Key': str(uuid4())})
    assert response.status_code == 404
    assert browser.state()['revision'] == 1
    assert alice.get('/api/state').json['revision'] == 1
    assert [row['title'] for row in browser.client.get('/api/export').json['tables']['tasks']] == ['原来的任务']
    assert [row['title'] for row in alice.get('/api/export').json['tables']['tasks']] == ['Alice 的任务']
    owner_backup = browser.client.get('/api/export').json
    response = alice.post('/api/restore', json={'backup': owner_backup, 'confirmation':'恢复',
        'revision':1, 'day':alice_state['day']}, headers={
        'X-CSRF-Token': alice.get('/api/session').json['csrf'], 'Idempotency-Key': str(uuid4())})
    assert response.status_code == 200
    assert [t['title'] for t in alice.get('/api/state').json['tasks']] == ['原来的任务']
    assert [t['title'] for t in browser.state()['tasks']] == ['原来的任务']
    current = alice.get('/api/state').json
    changed = alice.post('/api/settings', json={'default_minutes': 90, 'revision':current['revision'],
                         'day':current['day']}, headers={'X-CSRF-Token': alice.get('/api/session').json['csrf'],
                         'Idempotency-Key':str(uuid4())})
    assert changed.status_code == 200
    assert changed.json['settings']['default_minutes'] == 90
    assert browser.state()['settings']['default_minutes'] == 120


def test_account_password_reset_and_server_zip_backup(app, browser, tmp_path):
    set_invite(app)
    alice, response = register(app)
    assert response.status_code == 200
    add_task(alice, 'Alice 私人任务')
    backup = tmp_path / 'all-users.zip'
    command = app.test_cli_runner().invoke(args=['backup', str(backup)])
    assert command.exit_code == 0, command.output
    with zipfile.ZipFile(backup) as archive:
        archive.extractall(tmp_path / 'restored')
        assert len(archive.namelist()) == 2
    with sqlite3.connect(tmp_path / 'restored' / 'day-enough.sqlite') as db:
        assert [row[0] for row in db.execute('SELECT username FROM users ORDER BY username')] == ['alice', 'owner']
    restored = create_app({'TESTING':True, 'DATABASE':str(tmp_path / 'restored' / 'day-enough.sqlite'),
                           'SECRET_KEY':'restored-test-key', 'TODAY':'2026-09-14'})
    client = restored.test_client()
    csrf = client.get('/api/session').json['csrf']
    response = client.post('/api/login', json={'username':'alice', 'password':'alice-password-123'},
                           headers={'X-CSRF-Token':csrf})
    assert response.status_code == 200
    assert [t['title'] for t in client.get('/api/state').json['tasks']] == ['Alice 私人任务']
    assert Browser(restored).state()['tasks'] == browser.state()['tasks']
    result = app.test_cli_runner().invoke(args=['set-password','--username','alice'],
                                          input='new-alice-password-123\nnew-alice-password-123\n')
    assert result.exit_code == 0, result.output
    assert alice.get('/api/state').status_code == 401
    assert browser.client.get('/api/state').status_code == 200
    fresh = app.test_client()
    csrf = fresh.get('/api/session').json['csrf']
    assert fresh.post('/api/login', json={'username':'alice','password':'new-alice-password-123'},
                      headers={'X-CSRF-Token':csrf}).status_code == 200
