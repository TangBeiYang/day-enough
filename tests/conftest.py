from uuid import uuid4
import pytest
from day_enough import create_app
from day_enough.db import get_db, set_value
from werkzeug.security import generate_password_hash

PASSWORD = 'test-only-password-123'


class Browser:
    def __init__(self, app):
        self.client = app.test_client()
        self.csrf = self.client.get('/api/session').json['csrf']
        response = self.client.post('/api/login', json={'username': 'owner', 'password': PASSWORD}, headers={'X-CSRF-Token': self.csrf})
        assert response.status_code == 200
        self.csrf = response.json['csrf']

    def state(self):
        response = self.client.get('/api/state')
        assert response.status_code == 200, response.json
        return response.json

    def post(self, path, data=None, base=None, key=None):
        base = base if base is not None else self.state()
        body = {**(data or {}), 'revision': base['revision'], 'day': base['day']}
        return self.client.post('/api' + path, json=body, headers={
            'X-CSRF-Token': self.csrf, 'Idempotency-Key': key or str(uuid4())})

    def add(self, **kwargs):
        response = self.post('/tasks', {'title': '课程报告', 'due_date': '2026-09-17',
            'remaining_minutes': 180, 'energy': 'medium', 'consequence': 'high', 'next_step': '', **kwargs})
        assert response.status_code == 200, response.json
        return next(t for t in response.json['tasks'] if t['title'] == kwargs.get('title', '课程报告'))


@pytest.fixture
def app(tmp_path):
    app = create_app({'TESTING': True, 'DATABASE': str(tmp_path / 'test.sqlite'),
                      'SECRET_KEY': 'test-secret-key', 'TODAY': '2026-09-14'})
    with app.app_context():
        set_value(get_db(), 'password_hash', generate_password_hash(PASSWORD))
    return app


@pytest.fixture
def browser(app):
    return Browser(app)
