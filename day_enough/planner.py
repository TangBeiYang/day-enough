"""Deterministic daily allocation, independent of HTTP and storage."""
from datetime import date
from math import ceil

ENERGY_SHARE = {'low': .25, 'medium': .6, 'high': 1.0}
LABELS = {'low': '低', 'medium': '中', 'high': '高'}


def days_left(task, today):
    if not task['due_date']:
        return None
    return (date.fromisoformat(task['due_date']) - today).days


def target_days(task, today):
    target = task.get('planned_date') or task['due_date']
    return (date.fromisoformat(target) - today).days if target else None


def recommend(tasks, today, budget, energy, already_worked=0, high_worked=0, excluded=()):
    available = max(0, budget - already_worked)
    high_available = max(0, int(budget * ENERGY_SHARE[energy]) - high_worked)
    candidates = [t for t in tasks if t['status'] == 'active'
                  and t['remaining_minutes'] > 0 and t['id'] not in excluded]

    def urgency(t):
        remaining_days = target_days(t, today)
        if remaining_days is None:
            return {'low': 1, 'medium': 1.5, 'high': 2}[t['consequence']]
        days = max(1, remaining_days + 1)
        # Daily effort pressure lets long projects compete before the last day.
        pressure = t['remaining_minutes'] / days
        weight = {'low': 1, 'medium': 1.5, 'high': 2}[t['consequence']]
        return pressure * weight + (240 if remaining_days <= 0 else 60 / days)

    candidates.sort(key=lambda t: (-urgency(t), t['due_date'] or '9999-12-31', t['id']))
    result = []
    for task in candidates:
        if available <= 0:
            break
        days = days_left(task, today)
        goal_days = target_days(task, today)
        share = (ceil(task['remaining_minutes'] / max(1, goal_days + 1) / 15) * 15
                 if goal_days is not None else 30)
        # At least a meaningful short session, unless the task has less remaining.
        target = max(30, share)
        if task.get('recurrence_id'):
            target = task['remaining_minutes']
        minutes = min(task['remaining_minutes'], target, available)
        if task['energy'] == 'high':
            minutes = min(minutes, high_available)
        if minutes <= 0:
            continue
        if days is None:
            reason = f'无截止日期 · 后果{LABELS[task["consequence"]]} · 安排一个可推进份额'
        else:
            deadline = '已过截止日期' if days < 0 else ('今天截止' if days == 0 else f'距截止还有 {days} 天')
            reason = f'{deadline} · 后果{LABELS[task["consequence"]]} · 按剩余工作量分配'
        if task.get('planned_date'):
            label = '已超过计划完成日期' if task['planned_date'] < today.isoformat() else '计划完成'
            reason = f'{label} {task["planned_date"]} · ' + reason
        result.append({'task_id': task['id'], 'planned_minutes': minutes, 'reason': reason})
        available -= minutes
        if task['energy'] == 'high':
            high_available -= minutes
    return result


def risks(tasks, today, default_minutes, today_budget, worked, energy, high_worked, planned):
    """Conservative deadline feasibility checks; estimates, not promises."""
    active = sorted([t for t in tasks if t['status'] == 'active'
                     and t['remaining_minutes'] > 0 and t['due_date']],
                    key=lambda t: (t['due_date'], t['id']))
    warnings = []
    cumulative = 0
    high_cumulative = 0
    warned_capacity = False
    warned_high = False
    for task in active:
        days = days_left(task, today)
        cumulative += task['remaining_minutes']
        if task['energy'] == 'high':
            high_cumulative += task['remaining_minutes']
        if days < 0:
            warnings.append(f'「{task["title"]}」已过截止日期，仍需约 {task["remaining_minutes"]} 分钟。')
        capacity = max(0, today_budget - worked) + max(0, days) * default_minutes
        if cumulative > capacity and not warned_capacity:
            warnings.append(f'截至 {task["due_date"]} 的任务合计还需 {cumulative} 分钟，'
                            f'按每日默认时间估算，仅有 {capacity} 分钟，缺口约 {cumulative-capacity} 分钟。')
            warned_capacity = True
        high_capacity = max(0, int(today_budget * ENERGY_SHARE[energy]) - high_worked) + max(0, days) * int(default_minutes * .6)
        if high_cumulative > high_capacity and not warned_high:
            warnings.append('高消耗任务可能超过精力预算；未来暂按「一般」状态估算，可调整任务范围或安排。')
            warned_high = True
        if days <= 0 and planned.get(task['id'], 0) < task['remaining_minutes']:
            warnings.append(f'「{task["title"]}」今天安排的份额不足以完成全部剩余工作。')
    return warnings
