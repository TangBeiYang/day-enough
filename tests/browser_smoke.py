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
                for title,minutes,energy,step,due in [
                    ('课程报告 · 整理文献',240,'high','先整理三篇参考文献，记下各自的研究问题。','2026-09-17'),
                    ('数据结构 · 每日练习',60,'medium','完成两道二叉树练习题。','2026-09-17'),
                    ('长期阅读',15,'low','读完当前章节。','')]:
                    page.get_by_role('button',name='＋ 新建任务',exact=True).click()
                    page.get_by_label('任务名称',exact=True).fill(title)
                    if due:
                        page.locator('#task-due').fill(due)
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
                expect(page.get_by_text('无截止日期', exact=True)).to_be_visible()
                page.locator('.library-card').filter(has=page.get_by_role('heading',name='长期阅读',exact=True)).get_by_role('button',name='编辑',exact=True).click()
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
                # Ordinary planned dates and recurring task management.
                page.get_by_role('button',name='＋ 新建任务',exact=True).click()
                page.get_by_label('任务名称',exact=True).fill('后天读书')
                page.locator('#task-planned').fill('2026-09-16')
                page.get_by_role('button',name='保存任务',exact=True).click()
                expect(page.locator('#task-dialog')).not_to_be_visible()
                for name,frequency,minutes in [('每天背单词','daily','20'),('每周笔记','weekly','60'),('每月总结','monthly','30')]:
                    page.get_by_role('button',name='＋ 新建任务',exact=True).click()
                    page.get_by_label('任务类型').select_option('recurring')
                    expect(page.locator('#task-planned')).to_have_value('2026-09-14')
                    page.get_by_label('任务名称',exact=True).fill(name)
                    page.get_by_label('每次预计多少分钟').fill(minutes)
                    page.get_by_label('重复频率').select_option(frequency)
                    if frequency=='weekly':
                        page.get_by_label('周一',exact=True).check()
                        page.get_by_label('周三',exact=True).check()
                        page.get_by_label('如果当天没做完').select_option('carry')
                    if frequency=='monthly':
                        page.get_by_label('每月哪一天').select_option('31')
                        page.get_by_label('计划当天必须完成').check()
                    page.get_by_role('button',name='保存任务',exact=True).click()
                    expect(page.locator('#task-dialog')).not_to_be_visible()
                expect(page.locator('.scheduled-notice')).to_contain_text('每天背单词')
                page.get_by_label('今天有多少可支配时间').fill('240')
                page.get_by_role('button',name='重新安排今天').click()
                page.locator('#confirm-submit').click()
                expect(page.locator('#confirm-dialog')).not_to_be_visible()
                expect(page.locator('.task-card').filter(has=page.get_by_role('heading',name='后天读书',exact=True))).to_have_count(0)
                vocabulary = page.locator('.task-card').filter(has=page.get_by_role('heading',name='每天背单词',exact=True))
                expect(vocabulary.locator('.task-time')).to_contain_text('20')
                vocabulary.get_by_role('button',name='完成今日份额').click()
                expect(vocabulary).to_have_class('card task-card finished')
                page.get_by_role('link',name='我的任务').click()
                page.get_by_role('button',name='周期任务 · 3',exact=True).click()
                expect(page.locator('.recurrence-card')).to_have_count(3)
                rule = page.locator('.recurrence-card').filter(has=page.get_by_role('heading',name='每天背单词',exact=True))
                expect(rule).to_contain_text('重复中')
                rule.get_by_role('button',name='编辑规则').click()
                page.get_by_label('每次预计多少分钟').fill('25')
                page.get_by_role('button',name='保存任务',exact=True).click()
                expect(page.locator('#task-dialog')).not_to_be_visible()
                rule.locator('summary').click()
                expect(rule.locator('.library-card')).to_have_count(1)
                expect(rule.locator('.library-card')).to_contain_text('累计投入 20 分钟')
                rule.get_by_role('button',name='暂停重复').click()
                page.locator('#confirm-submit').click()
                expect(page.locator('#confirm-dialog')).not_to_be_visible()
                app.config['TODAY']='2026-09-15'
                page.get_by_role('button',name='↻ 刷新').click()
                expect(rule).to_contain_text('已暂停')
                expect(rule.locator('summary')).to_contain_text('（1）')
                rule.get_by_role('button',name='恢复重复').click()
                page.locator('#confirm-submit').click()
                expect(page.locator('#confirm-dialog')).not_to_be_visible()
                expect(rule.locator('summary')).to_contain_text('（2）')
                page.get_by_role('link',name='今天',exact=True).click()
                page.get_by_role('button',name='生成今日安排').click()
                expect(page.locator('.task-card').filter(has=page.get_by_role('heading',name='每周笔记',exact=True))).to_have_count(1)
                expect(page.locator('.task-card').filter(has=page.get_by_role('heading',name='后天读书',exact=True))).to_have_count(0)
                vocabulary = page.locator('.task-card').filter(has=page.get_by_role('heading',name='每天背单词',exact=True))
                expect(vocabulary.locator('.task-time')).to_contain_text('25')
                vocabulary.get_by_role('button',name='记一部分').click()
                page.get_by_label('这次投入了多少分钟').fill('5')
                page.get_by_role('button',name='记录进展',exact=True).click()
                expect(page.locator('#work-dialog')).not_to_be_visible()
                app.config['TODAY']='2026-09-16'
                page.get_by_role('button',name='↻ 刷新').click()
                expect(page.locator('.scheduled-notice')).to_contain_text('后天读书')
                page.get_by_role('link',name='我的任务').click()
                rule = page.locator('.recurrence-card').filter(has=page.get_by_role('heading',name='每天背单词',exact=True))
                rule.locator('summary').click()
                missed = rule.locator('.library-card').filter(has_text='周期 · 2026-09-15')
                expect(missed).to_contain_text('未完成 · 不补做')
                expect(missed).to_contain_text('累计投入 5 分钟')
                page.screenshot(path=str(screenshots/'recurrences.png'),full_page=True)
                # Backups with actual recurrence rules also survive the UI flow.
                page.get_by_role('link',name='设置',exact=True).click()
                with page.expect_download() as download:
                    page.get_by_role('link',name='↓ 导出 JSON 备份').click()
                recurring_backup=Path(directory)/'recurrences.json';download.value.save_as(recurring_backup)
                page.locator('#backup-file').set_input_files(recurring_backup)
                page.get_by_label('输入「恢复」以确认替换').fill('恢复')
                page.get_by_role('button',name='替换并恢复').click()
                expect(page.locator('#confirm-dialog')).not_to_be_visible()
                page.get_by_role('link',name='我的任务').click()
                expect(page.locator('.recurrence-card')).to_have_count(3)
                page.get_by_role('button',name='＋ 新建任务',exact=True).click()
                page.get_by_label('任务类型').select_option('recurring')
                page.get_by_label('重复频率').select_option('weekly')
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(screenshots/'recurrence-form-mobile.png'),full_page=True)
                page.locator('#task-dialog [data-close]').first.click()
                page.screenshot(path=str(screenshots/'mobile.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile horizontal overflow'
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown();thread.join(timeout=5)
    print('Browser smoke passed: existing workflows, ordinary planned date, daily/weekly/monthly rules, pause/resume, independent progress, missed history, v2 restore, mobile; no JS/CSP errors.')


if __name__=='__main__':
    main()
