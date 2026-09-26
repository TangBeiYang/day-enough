"""Read-only multi-day trial used for today's automatic recommendations."""
from datetime import date, timedelta
from math import ceil

from .capacity import minutes_on
from .recurrence import cycle_end, cycle_start, next_occurrence, occurrence_deadline

ENERGY_SHARE = {'low': .25, 'medium': .6, 'high': 1.0}
LABELS = {'low': '低', 'medium': '中', 'high': '高'}
WEIGHT = {'low': 1, 'medium': 1.5, 'high': 2}


def _preview_tasks(tasks, rules, today, last):
    work = [dict(task, _available=today.isoformat(), _remaining=task['remaining_minutes'])
            for task in tasks if task['status'] == 'active' and task['remaining_minutes'] > 0]
    for rule in rules:
        if rule['status'] != 'active':
            continue
        occurrence = rule['next_date']
        while occurrence <= last.isoformat():
            available = max(today.isoformat(), rule['start_date'], cycle_start(rule['frequency'], occurrence))
            if available <= last.isoformat():
                work.append({'id': f"future:{rule['id']}:{occurrence}", 'title': rule['title'],
                             'due_date': occurrence_deadline(rule, occurrence), 'planned_date': occurrence,
                             'cycle_end': cycle_end(rule['frequency'], occurrence),
                             'missed_policy': rule['missed_policy'], 'consequence': rule['consequence'],
                             'energy': rule['energy'], 'recurrence_id': rule['id'],
                             '_remaining': rule['minutes'], '_available': available, '_virtual': True})
            after = (date.fromisoformat(occurrence) + timedelta(days=1)).isoformat()
            occurrence = next_occurrence(rule['frequency'], rule['weekdays'], rule['month_day'],
                                         cycle_start(rule['frequency'], rule['start_date']), after)
    return work


def _reason(task, today, minutes, kind, stage_title):
    due = task.get('due_date')
    if due:
        distance = (date.fromisoformat(due) - today).days
        label = '已过截止日期' if distance < 0 else ('今天截止' if distance == 0 else f'距截止还有 {distance} 天')
        reason = f'{label} · 后果{LABELS[task["consequence"]]}'
    else:
        reason = f'无截止日期 · 后果{LABELS[task["consequence"]]}'
    if task.get('planned_date'):
        label = '已超过计划完成日期' if task['planned_date'] < today.isoformat() else '计划完成'
        reason = f'{label} {task["planned_date"]} · ' + reason
    if kind == 'stage':
        reason = f'阶段「{stage_title}」需要推进 · ' + reason
    elif kind == 'carry':
        reason = '阶段目标待继续 · ' + reason
    return f'{reason} · 建议投入 {minutes} 分钟'


def trial(tasks, today, budget, energy, already_worked=0, high_worked=0, excluded=(),
          *, default_minutes=120, weekly_minutes=None, date_overrides=None,
          stages=(), recurrences=(), fixed_today=None, locked_today=False):
    """Return today's picks and shortfalls; never mutate caller data or future plans."""
    weekly = weekly_minutes if weekly_minutes is not None else [None] * 7
    overrides = date_overrides if date_overrides is not None else {}
    last = today + timedelta(days=34)
    relevant = [date.fromisoformat(stage['end_date']) for stage in stages
                if stage['status'] == 'active' and today.isoformat() <= stage['end_date']]
    relevant += [date.fromisoformat(task['due_date']) for task in tasks
                 if task['status'] == 'active' and task.get('due_date') and today.isoformat() <= task['due_date']]
    if relevant:
        last = max(last, min(max(relevant), today + timedelta(days=59)))
    days = [today + timedelta(days=i) for i in range((last - today).days + 1)]
    # Look farther ahead for pacing than for detailed trial, so a distant goal is not
    # mistakenly treated as if all its remaining work must fit in the next 60 days.
    capacities = [budget] + [minutes_on(today + timedelta(days=i), default_minutes, weekly, overrides)
                             for i in range(1, 366)]
    capacity_prefix = [0]
    for minutes in capacities:
        capacity_prefix.append(capacity_prefix[-1] + minutes)
    work = _preview_tasks(tasks, recurrences, today, last)
    by_id = {task['id']: task for task in work}
    goals = []
    for stage in stages:
        if stage['status'] != 'active':
            continue
        for target in stage['targets']:
            task = by_id.get(target['task_id'])
            if not task or target['completed']:
                continue
            needed = (task['_remaining'] if target['mode'] == 'complete' else
                      max(0, target['target_minutes'] - target['progress_minutes']))
            if needed:
                goals.append({'task_id': task['id'], 'title': stage['title'],
                              'start': stage['start_date'], 'end': stage['end_date'], 'need': needed})

    def apply(task, minutes, day):
        task['_remaining'] -= minutes
        task['_last_work_day'] = day.isoformat()
        for goal in goals:
            if goal['task_id'] == task['id'] and day.isoformat() >= goal['start']:
                goal['need'] = max(0, goal['need'] - minutes)
        if task['_remaining'] == 0:
            for goal in goals:
                if goal['task_id'] == task['id']:
                    goal['need'] = 0

    fixed = fixed_today or {}
    if locked_today:
        for task_id, minutes in fixed.items():
            if task_id in by_id:
                apply(by_id[task_id], min(by_id[task_id]['_remaining'], minutes), today)
    picks, shortfalls = [], []
    for index, day in enumerate(days):
        available = max(0, capacities[index] - (already_worked if index == 0 else 0)
                        - (sum(fixed.values()) if index == 0 and locked_today else 0))
        high_available = max(0, int(capacities[index] * ENERGY_SHARE[energy if index == 0 else 'medium'])
                             - (high_worked if index == 0 else 0)
                             - (sum(minutes for task_id, minutes in fixed.items()
                                    if by_id.get(task_id, {}).get('energy') == 'high')
                                if index == 0 and locked_today else 0))
        if available and not (index == 0 and locked_today):
            candidates = []
            for task in work:
                if (task['_remaining'] <= 0 or task['_available'] > day.isoformat() or
                        (index == 0 and task['id'] in excluded)):
                    continue
                hard = task.get('due_date') or (task.get('cycle_end') if task.get('missed_policy') == 'skip' else '')
                obligations = []
                if hard:
                    obligations.append(('hard', max(hard, day.isoformat()), task['_remaining'], ''))
                if task.get('planned_date'):
                    obligations.append(('planned', max(task['planned_date'], day.isoformat()),
                                        task['_remaining'], ''))
                for goal in goals:
                    if goal['task_id'] == task['id'] and goal['need'] and goal['start'] <= day.isoformat():
                        obligations.append(('stage', max(goal['end'], day.isoformat()),
                                            min(goal['need'], task['_remaining']), goal['title']))
                priority = (-1, 0, 0, 0)
                desired = min(30, task['_remaining'])
                chosen_kind, chosen_title = 'undated', ''
                for kind, end, needed, title in obligations:
                    end_distance = (date.fromisoformat(end) - today).days
                    end_index = min(max(index, end_distance), 365)
                    future = capacity_prefix[end_index + 1] - capacity_prefix[index + 1]
                    # Other hard deadlines share this future capacity. This includes
                    # predicted recurrence instances that do not exist in storage yet.
                    future -= sum(other['_remaining'] for other in work
                                  if other['id'] != task['id'] and other['_available'] <= end
                                  and day.isoformat() < (other.get('due_date') or
                                      (other.get('cycle_end') if other.get('missed_policy') == 'skip' else '')) <= end)
                    future = max(0, future)
                    if end_distance > 365:
                        future = max(future, needed)
                    total = max(1, available + future)
                    required = max(0, needed - future)
                    pace = min(task['_remaining'], max(20, ceil(needed * available / total / 5) * 5,
                                                        required))
                    tier = (4 if kind == 'hard' and required else
                            3 if kind == 'stage' and required else 2)
                    rank = (tier, needed / total, -(date.fromisoformat(end) - day).days,
                            WEIGHT[task['consequence']])
                    if rank > priority:
                        priority, desired, chosen_kind, chosen_title = rank, pace, kind, title
                if not obligations:
                    carry = any(goal['task_id'] == task['id'] and goal['need'] for goal in goals)
                    last_work = task.get('_last_work_day', day.isoformat())
                    idle_days = max(0, (day - date.fromisoformat(last_work)).days)
                    tier = 2 if idle_days >= 14 else 1 if idle_days >= 7 or carry else 0
                    priority = (tier, min(1, idle_days / 21) + WEIGHT[task['consequence']] / 10,
                                0, 0)
                    chosen_kind = 'carry' if carry else 'undated'
                candidates.append((priority, task['id'], task, desired, chosen_kind, chosen_title))
            candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            for _, _, task, desired, kind, title in candidates:
                if available <= 0:
                    break
                minutes = min(desired, task['_remaining'], available)
                if task['energy'] == 'high':
                    minutes = min(minutes, high_available)
                if minutes <= 0:
                    continue
                apply(task, minutes, day)
                available -= minutes
                if task['energy'] == 'high':
                    high_available -= minutes
                if index == 0 and not task.get('_virtual'):
                    picks.append({'task_id': task['id'], 'planned_minutes': minutes,
                                  'reason': _reason(task, today, minutes, kind, title)})
        for goal in goals:
            if goal['end'] == day.isoformat() and goal['need']:
                shortfalls.append(f'阶段「{goal["title"]}」截至 {goal["end"]} 预计还差约 {goal["need"]} 分钟；可调整目标或时间预算。')
        for task in work:
            if task.get('due_date') == day.isoformat() and task['_remaining'] > 0:
                shortfalls.append(f'「{task["title"]}」截至 {day.isoformat()} 预计还差约 {task["_remaining"]} 分钟；请调整范围或时间预算。')
    if len(shortfalls) > 5:
        shortfalls = shortfalls[:5] + [f'未来试排还有 {len(shortfalls)-5} 项预计排不下；请检查时间预算和目标。']
    return picks, shortfalls


def recommend(tasks, today, budget, energy, already_worked=0, high_worked=0, excluded=(), **options):
    return trial(tasks, today, budget, energy, already_worked, high_worked, excluded, **options)[0]


def risks(tasks, today, default_minutes, today_budget, worked, energy, high_worked, planned,
          *, locked_today=False, **options):
    _, warnings = trial(tasks, today, today_budget, energy, worked, high_worked,
                        default_minutes=default_minutes, locked_today=locked_today,
                        fixed_today=planned, **options)
    for task in tasks:
        if task['status'] != 'active' or task['remaining_minutes'] <= 0 or not task.get('due_date'):
            continue
        days = (date.fromisoformat(task['due_date']) - today).days
        if days < 0:
            warnings.insert(0, f'「{task["title"]}」已过截止日期，仍需约 {task["remaining_minutes"]} 分钟。')
        elif days == 0 and planned.get(task['id'], 0) < task['remaining_minutes']:
            warnings.append(f'「{task["title"]}」今天安排的份额不足以完成全部剩余工作。')
    idle = [task['title'] for task in tasks if task['status'] == 'active'
            and task['remaining_minutes'] > 0 and not task.get('due_date')
            and not task.get('planned_date') and task['id'] not in planned
            and (today - date.fromisoformat(task.get('_last_work_day', today.isoformat()))).days >= 14]
    if idle:
        names = '、'.join(f'「{title}」' for title in idle[:3])
        warnings.append(f'{names}{"等" if len(idle) > 3 else ""}已至少两周未推进；可以安排一段时间，或调整任务范围。')
    return list(dict.fromkeys(warnings))
