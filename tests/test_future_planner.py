from copy import deepcopy
from datetime import date

from day_enough.planner import recommend
from test_stages import create_stage, save_target
from test_recurrence import add_rule


def test_capacity_settings_backup_and_old_restore(browser):
    weekly = [30, None, None, None, None, 180, 60]
    overrides = {'2026-09-15': 0}
    result = browser.post('/settings', {'default_minutes': 120, 'weekly_minutes': weekly,
                                        'date_overrides': overrides})
    assert result.status_code == 200, result.json
    assert result.json['settings']['weekly_minutes'] == weekly
    assert result.json['settings']['date_overrides'] == overrides
    backup = browser.client.get('/api/export').json
    assert backup['version'] == 7 and backup['weekly_minutes'] == weekly
    for bad in ([None] * 6, [True] + [None] * 6):
        assert browser.post('/settings', {'default_minutes': 120, 'weekly_minutes': bad}).status_code == 400
    assert browser.post('/settings', {'default_minutes': 120,
                                      'date_overrides': {'2026-02-30': 30}}).status_code == 400
    assert browser.client.get('/api/export').json == backup
    broken = deepcopy(backup)
    broken['date_overrides'] = {'2026-09-15': 1000}
    assert browser.post('/restore', {'backup': broken, 'confirmation': '恢复'}).status_code == 400
    assert browser.client.get('/api/export').json == backup
    assert browser.post('/restore', {'backup': backup, 'confirmation': '恢复'}).status_code == 200
    old = deepcopy(backup)
    old['version'] = 6
    del old['weekly_minutes'], old['date_overrides']
    restored = browser.post('/restore', {'backup': old, 'confirmation': '恢复'})
    assert restored.status_code == 200
    assert restored.json['settings']['weekly_minutes'] == [None] * 7
    assert restored.json['settings']['date_overrides'] == {}


def test_hard_deadline_and_stage_share_daily_capacity(browser):
    deadline = browser.add(title='明天交报告', due_date='2026-09-15', remaining_minutes=120)
    reading = browser.add(title='周末阅读', due_date='', remaining_minutes=60)
    add_rule(browser, frequency='daily', remaining_minutes=20, title='背单词')
    stage = create_stage(browser, title='这两天', end_date='2026-09-15')
    assert save_target(browser, stage, reading, 'minutes', 60).status_code == 200
    browser.post('/settings', {'default_minutes': 120,
                               'date_overrides': {'2026-09-15': 60}})
    result = browser.post('/plan', {'budget': 120, 'energy': 'high'}).json
    selected = {item['task_id']: item['planned_minutes'] for item in result['items']}
    assert deadline['id'] in selected and reading['id'] in selected
    assert sum(selected.values()) <= 120
    assert any('阶段「这两天」' in warning and '还差约' in warning
               for warning in result['warnings'])
    assert result['items'][0]['task_id'] == deadline['id']
    assert all(not task['id'].startswith('future:') for task in result['tasks'])
    assert result['plan']['budget'] == 120


def test_stage_priority_and_overlapping_goals_count_one_task(browser):
    focus = browser.add(title='阶段重点', due_date='', remaining_minutes=90)
    other = browser.add(title='其他任务', due_date='', remaining_minutes=90)
    first = create_stage(browser, title='计划甲', end_date='2026-09-15')
    create_stage(browser, title='计划乙', end_date='2026-09-15')
    second = next(stage for stage in browser.state()['stages'] if stage['title'] == '计划乙')
    assert save_target(browser, first, focus, 'minutes', 60).status_code == 200
    assert save_target(browser, second, focus, 'minutes', 60).status_code == 200
    result = browser.post('/plan', {'budget': 60, 'energy': 'high'}).json
    assert result['items'][0]['task_id'] == focus['id']
    assert sum(item['planned_minutes'] for item in result['items']) <= 60
    assert not any('阶段「计划甲」' in warning or '阶段「计划乙」' in warning
                   for warning in result['warnings'])
    assert next(task for task in result['tasks'] if task['id'] == other['id'])['remaining_minutes'] == 90


def test_competing_real_deadlines_share_tomorrows_capacity(browser):
    first = browser.add(title='报告甲', due_date='2026-09-15', remaining_minutes=60)
    second = browser.add(title='报告乙', due_date='2026-09-15', remaining_minutes=60)
    reading = browser.add(title='阶段阅读', due_date='', remaining_minutes=60)
    stage = create_stage(browser, title='这两天', end_date='2026-09-15')
    assert save_target(browser, stage, reading, 'minutes', 60).status_code == 200
    browser.post('/settings', {'default_minutes': 60})
    result = browser.post('/plan', {'budget': 60, 'energy': 'high'}).json
    assert result['items'][0]['task_id'] in (first['id'], second['id'])
    assert result['items'][0]['planned_minutes'] == 60
    assert any('阶段「这两天」' in warning for warning in result['warnings'])
    assert not any('报告甲' in warning or '报告乙' in warning for warning in result['warnings'])


def test_future_hard_deadline_beats_soft_today_when_tomorrow_has_no_time():
    tasks = [
        {'id': 'soft', 'title': '自己希望今天完成', 'status': 'active', 'remaining_minutes': 60,
         'planned_date': '2026-09-14', 'due_date': '', 'consequence': 'high', 'energy': 'medium'},
        {'id': 'hard', 'title': '明天必须交', 'status': 'active', 'remaining_minutes': 60,
         'planned_date': '', 'due_date': '2026-09-15', 'consequence': 'medium', 'energy': 'medium'},
    ]
    picks = recommend(tasks, date(2026, 9, 14), 60, 'high',
                      date_overrides={'2026-09-15': 0})
    assert picks[0]['task_id'] == 'hard'
    assert sum(item['planned_minutes'] for item in picks) <= 60


def test_long_ignored_undated_task_gets_a_turn():
    tasks = [
        {'id': 'recent', 'title': '刚推进过', 'status': 'active', 'remaining_minutes': 90,
         'due_date': '', 'consequence': 'high', 'energy': 'medium',
         '_last_work_day': '2026-09-13'},
        {'id': 'idle', 'title': '两周没碰', 'status': 'active', 'remaining_minutes': 90,
         'due_date': '', 'consequence': 'low', 'energy': 'medium',
         '_last_work_day': '2026-08-31'},
    ]
    picks = recommend(tasks, date(2026, 9, 14), 30, 'high')
    assert picks[0]['task_id'] == 'idle'


def test_empty_saved_plan_does_not_hide_today_shortfall(browser):
    browser.add(title='今晚交', due_date='2026-09-14', remaining_minutes=60)
    result = browser.post('/plan', {'budget': 0, 'energy': 'high'}).json
    assert result['items'] == []
    assert any('今晚交' in warning and '还差约 60 分钟' in warning
               for warning in result['warnings'])


def test_distant_deadline_uses_capacity_beyond_trial_window():
    task = {'id': 'distant', 'title': '远期项目', 'status': 'active',
            'remaining_minutes': 1000, 'due_date': '2027-03-01',
            'consequence': 'medium', 'energy': 'medium'}
    picks = recommend([task], date(2026, 9, 14), 60, 'high')
    assert picks[0]['planned_minutes'] <= 30
