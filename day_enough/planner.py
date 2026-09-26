"""Public interface for deterministic daily planning."""
from datetime import date

from .future_planner import recommend, risks


def days_left(task, today):
    return (date.fromisoformat(task['due_date']) - today).days if task.get('due_date') else None


def target_days(task, today):
    target = task.get('planned_date') or task.get('due_date')
    return (date.fromisoformat(target) - today).days if target else None
