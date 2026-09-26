import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path
import click
from werkzeug.security import generate_password_hash
from .db import connect, get_db, get_registry_db, set_value, user_db_path, value


def register(app):
    @app.cli.command('set-password')
    @click.option('--username', default='owner', help='要重置密码的用户名，默认 owner。')
    @click.password_option(confirmation_prompt=True)
    def set_password(username, password):
        """Initialize or reset an account password (invalidates existing logins)."""
        if not 12 <= len(password) <= 256:
            raise click.ClickException('密码须为 12–256 个字符。')
        from .api import username_field
        with app.test_request_context():
            username = username_field({'username': username})
        row = get_registry_db().execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        if not row:
            raise click.ClickException('用户名不存在。')
        if row['id'] != 'owner' and not Path(user_db_path(row['id'])).is_file():
            raise click.ClickException('账号数据文件不存在，请先从完整备份恢复。')
        db = get_db() if row['id'] == 'owner' else connect(user_db_path(row['id']))
        try:
            db.execute('BEGIN IMMEDIATE')
            try:
                set_value(db, 'password_hash', generate_password_hash(password))
                set_value(db, 'auth_version', int(value(db, 'auth_version')) + 1)
                db.commit()
            except Exception:
                db.rollback()
                raise
        finally:
            if row['id'] != 'owner':
                db.close()
        click.echo(f'{username} 的密码已设置，原有会话已失效。')

    @app.cli.command('set-invite-code')
    @click.password_option(confirmation_prompt=True, prompt='新的邀请码')
    def set_invite_code(password):
        """Set or rotate the registration invite code."""
        if not 3 <= len(password) <= 8:
            raise click.ClickException('邀请码须为 3–8 个字符。')
        db = get_registry_db()
        db.execute('BEGIN IMMEDIATE')
        try:
            set_value(db, 'invite_code_hash', generate_password_hash(password))
            db.commit()
        except Exception:
            db.rollback()
            raise
        click.echo('邀请码已更新，新注册立即使用新码。')

    @app.cli.command('disable-registration')
    def disable_registration():
        """Disable new registrations without affecting existing accounts."""
        db = get_registry_db()
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute("DELETE FROM meta WHERE key='invite_code_hash'")
            db.commit()
        except Exception:
            db.rollback()
            raise
        click.echo('已暂停新用户注册。')

    @app.cli.command('count-users')
    def count_users():
        """Show how many accounts have been registered."""
        db = get_registry_db()
        registered = db.execute("SELECT COUNT(*) FROM users WHERE id!='owner'").fetchone()[0]
        total = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        click.echo(f'已注册用户：{registered}；账号总数（含 owner）：{total}。')

    @app.cli.command('backup')
    @click.argument('destination', type=click.Path())
    def backup(destination):
        """Make a consistent SQLite backup while the app is running."""
        path = Path(destination).resolve()
        if path == Path(app.config['DATABASE']).resolve() or path.exists():
            raise click.ClickException('请使用新的备份文件路径，不能覆盖现有文件。')
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        accounts = get_registry_db().execute("SELECT id FROM users WHERE id!='owner'").fetchall()
        if accounts and path.suffix != '.zip':
            raise click.ClickException('多用户完整备份请使用 .zip 文件名。')
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            if path.suffix == '.zip':
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    registry_copy = root / 'day-enough.sqlite'
                    with closing(connect(app.config['DATABASE'])) as original, closing(sqlite3.connect(registry_copy)) as target:
                        original.backup(target)
                        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                            raise click.ClickException('备份完整性校验失败。')
                    with closing(sqlite3.connect(registry_copy)) as captured:
                        saved_ids = [row[0] for row in captured.execute("SELECT id FROM users WHERE id!='owner'")]
                    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                        archive.write(registry_copy, 'day-enough.sqlite')
                        for user_id in saved_ids:
                            name, source = f'users/{user_id}.sqlite', user_db_path(user_id)
                            if not Path(source).is_file():
                                raise click.ClickException('账号数据文件不存在，完整备份未完成。')
                            copy = root / name
                            copy.parent.mkdir(parents=True, exist_ok=True)
                            with closing(connect(source)) as original, closing(sqlite3.connect(copy)) as target:
                                original.backup(target)
                                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                                    raise click.ClickException('备份完整性校验失败。')
                            archive.write(copy, name)
            else:
                with sqlite3.connect(path) as target:
                    get_registry_db().backup(target)
                    if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise click.ClickException('备份完整性校验失败。')
        except Exception:
            path.unlink(missing_ok=True)
            raise
        click.echo(f'备份完成并通过完整性校验：{path}')
