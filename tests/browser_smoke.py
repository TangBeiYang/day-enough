"""Run real Chrome against an isolated temporary database, never personal data.
Usage: .venv/bin/python tests/browser_smoke.py
Requires optional playwright package and Google Chrome (or CHROME_BIN).
"""
import os
import sys
import tempfile
import threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from werkzeug.security import generate_password_hash
from day_enough import create_app
from day_enough.db import get_db, set_value


def main():
    screenshots=Path('test-results')
    screenshots.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        app=create_app({'TESTING':True,'DATABASE':str(Path(directory)/'browser.sqlite'),
                        'SECRET_KEY':'browser-test-only-secret','TODAY':'2026-09-14'})
        with app.app_context():
            set_value(get_db(),'password_hash',generate_password_hash('browser-test-password'))
        server=make_server('127.0.0.1',0,app,threaded=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        errors=[]
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.environ.get('CHROME_BIN','/usr/bin/google-chrome'),headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('console',lambda message:errors.append(message.text) if message.type=='error' and 'Content Security Policy' in message.text else None)
                page.goto(f'http://127.0.0.1:{server.server_port}')
                expect(page.locator('#login-screen')).to_be_visible()
                page.screenshot(path=str(screenshots/'login.png'),full_page=True)
                page.get_by_label('个人密码',exact=True).fill('browser-test-password')
                page.get_by_role('button',name='进入我的一天').click()
                expect(page.locator('#app')).to_be_visible()
                expect(page.get_by_role('heading',name='从一件小事开始')).to_be_visible()
                for title,minutes,energy,step in [
                    ('课程报告 · 整理文献',240,'high','先整理三篇参考文献，记下各自的研究问题。'),
                    ('数据结构 · 每日练习',60,'medium','完成两道二叉树练习题。'),
                    ('回复课程邮件',15,'low','确认小组展示的时间。')]:
                    page.get_by_role('button',name='＋ 新建任务',exact=True).click()
                    page.get_by_label('任务名称',exact=True).fill(title)
                    page.get_by_label('截止日期',exact=True).fill('2026-09-17')
                    page.get_by_label('预计还需多少分钟').fill(str(minutes))
                    page.get_by_label('需要的精力').select_option(energy)
                    page.get_by_label('具体下一步').fill(step)
                    page.get_by_role('button',name='保存任务',exact=True).click()
                    expect(page.locator('#task-dialog')).not_to_be_visible()
                page.get_by_role('button',name='生成今日安排').click()
                expect(page.locator('.task-card')).to_have_count(3)
                page.screenshot(path=str(screenshots/'today.png'),full_page=True)
                page.get_by_role('button',name='记一部分').first.click()
                page.get_by_label('这次投入了多少分钟').fill('15')
                page.get_by_role('button',name='记录进展',exact=True).click()
                expect(page.locator('#work-dialog')).not_to_be_visible()
                expect(page.locator('.stat-value').nth(1)).to_contain_text('15')
                page.get_by_role('button',name='完成今日份额').first.click()
                expect(page.locator('.task-card.finished')).to_have_count(1)
                page.reload()
                expect(page.locator('.task-card.finished')).to_have_count(1)
                page.get_by_role('link',name='我的任务').click()
                expect(page.locator('.library-card')).to_have_count(3)
                page.locator('.library-card').filter(has=page.get_by_role('heading',name='回复课程邮件',exact=True)).get_by_role('button',name='编辑',exact=True).click()
                page.get_by_label('任务名称',exact=True).fill('修改后的任务 <script>alert(1)</script>')
                page.get_by_role('button',name='保存任务',exact=True).click()
                expect(page.locator('#task-dialog')).not_to_be_visible()
                page.get_by_role('searchbox').fill('修改后的任务')
                expect(page.locator('.library-card')).to_have_count(1)
                expect(page.locator('.library-card h3')).to_have_text('修改后的任务 <script>alert(1)</script>')
                page.get_by_role('button',name='归档',exact=True).click()
                page.locator('#confirm-submit').click()
                expect(page.locator('#confirm-dialog')).not_to_be_visible()
                expect(page.locator('.library-card')).to_have_count(0)
                page.get_by_role('searchbox').fill('')
                page.screenshot(path=str(screenshots/'tasks.png'),full_page=True)
                page.get_by_role('link',name='设置',exact=True).click()
                page.get_by_label('每天默认可支配分钟').fill('150')
                page.get_by_role('button',name='保存设置',exact=True).click()
                expect(page.get_by_label('每天默认可支配分钟')).to_have_value('150')
                with page.expect_download() as download:
                    page.get_by_role('link',name='↓ 导出 JSON 备份').click()
                backup=Path(directory)/'export.json';download.value.save_as(backup)
                page.locator('#backup-file').set_input_files(backup)
                expect(page.locator('#confirm-dialog')).to_be_visible()
                page.get_by_label('输入「恢复」以确认替换').fill('恢复')
                page.get_by_role('button',name='替换并恢复').click()
                expect(page.locator('#confirm-dialog')).not_to_be_visible()
                page.screenshot(path=str(screenshots/'settings.png'),full_page=True)
                page.get_by_role('link',name='今天',exact=True).click()
                page.get_by_role('button',name='重新安排今天').click()
                page.locator('#confirm-submit').click()
                expect(page.locator('#confirm-dialog')).not_to_be_visible()
                # Second browser context has an independent cookie and reads the same data.
                second=browser.new_context()
                other=second.new_page()
                other.goto(f'http://127.0.0.1:{server.server_port}')
                other.get_by_label('个人密码',exact=True).fill('browser-test-password')
                other.get_by_role('button',name='进入我的一天').click()
                expect(other.locator('#app')).to_be_visible()
                expect(other.locator('.stat-value').nth(1)).to_have_text(page.locator('.stat-value').nth(1).inner_text())
                # Old dialog must not overwrite progress from another tab.
                page.get_by_role('button',name='记一部分').first.click()
                other.get_by_role('button',name='完成今日份额').first.click()
                expect(other.locator('.task-card.finished')).to_have_count(3)
                page.get_by_role('button',name='记录进展',exact=True).click()
                expect(page.locator('#work-form .form-error')).to_contain_text('其他页面已更新数据')
                page.locator('#work-dialog [data-close]').first.click()
                page.get_by_role('button',name='↻ 刷新').click()
                expect(page.get_by_role('heading',name='今天，可以到这里。')).to_be_visible()
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(screenshots/'mobile.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile horizontal overflow'
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown();thread.join(timeout=5)
    print('Browser smoke passed: login, tasks, plan, progress, refresh, editing/XSS, archive, settings, export/restore, two browsers/conflict, mobile; no JS/CSP errors.')


if __name__=='__main__':
    main()
