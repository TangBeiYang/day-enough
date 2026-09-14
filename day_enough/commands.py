import os
import sqlite3
from pathlib import Path
import click
from werkzeug.security import generate_password_hash
from .db import get_db, set_value, value


def register(app):
    @app.cli.command('set-password')
    @click.password_option(confirmation_prompt=True)
    def set_password(password):
        """Initialize or reset the personal password (invalidates existing logins)."""
        if not 12 <= len(password) <= 256:
            raise click.ClickException('密码须为 12–256 个字符。')
        db = get_db()
        db.execute('BEGIN IMMEDIATE')
        try:
            set_value(db, 'password_hash', generate_password_hash(password))
            set_value(db, 'auth_version', int(value(db, 'auth_version')) + 1)
            db.commit()
        except Exception:
            db.rollback()
            raise
        click.echo('个人密码已设置，其他会话已失效。')

    @app.cli.command('backup')
    @click.argument('destination', type=click.Path())
    def backup(destination):
        """Make a consistent SQLite backup while the app is running."""
        path = Path(destination).resolve()
        if path == Path(app.config['DATABASE']).resolve() or path.exists():
            raise click.ClickException('请使用新的备份文件路径，不能覆盖现有文件。')
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        target = sqlite3.connect(path)
        try:
            get_db().backup(target)
            result = target.execute('PRAGMA integrity_check').fetchone()[0]
            if result != 'ok':
                raise click.ClickException('备份完整性校验失败。')
        finally:
            target.close()
        click.echo(f'备份完成并通过完整性校验：{path}')
