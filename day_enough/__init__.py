import os
import secrets
from datetime import timedelta
from pathlib import Path
from flask import Flask, g, jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from .db import connect, init_db


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    instance = Path(os.environ.get('DAY_ENOUGH_DATA', app.instance_path))
    instance.mkdir(parents=True, exist_ok=True, mode=0o700)
    app.config.from_mapping(
        DATABASE=str(instance / 'day-enough.sqlite'),
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
        SESSION_COOKIE_NAME='day_enough', SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Strict',
        SESSION_COOKIE_SECURE=os.environ.get('DAY_ENOUGH_SECURE_COOKIE') == '1',
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get('SECRET_KEY'):
        key_path = instance / 'secret.key'
        try:
            fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'w') as stream:
                stream.write(secrets.token_hex(32))
        app.config['SECRET_KEY'] = key_path.read_text().strip()
        if not app.config['SECRET_KEY']:
            raise RuntimeError('secret.key 为空，请停止服务后重新初始化。')
    db = connect(app.config['DATABASE'])
    try:
        init_db(db)
    finally:
        db.close()
    os.chmod(app.config['DATABASE'], 0o600)

    @app.teardown_appcontext
    def close_db(error=None):
        db = g.pop('db', None)
        if db:
            db.close()

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if not request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    from .api import bp
    from .commands import register
    app.register_blueprint(bp)
    register(app)
    return app
