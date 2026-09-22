"""Calendar recurrence and lazy materialization inside the caller's transaction."""
import calendar
import json
from datetime import date, timedelta
from uuid import uuid4


def next_occurrence(frequency, weekdays, month_day, start, on_or_after):
    day = max(date.fromisoformat(start), date.fromisoformat(on_or_after))
    if frequency == 'daily':
        return day.isoformat()
    if frequency == 'weekly':
        day += timedelta(days=min((weekday - day.weekday()) % 7 for weekday in weekdays))
        return day.isoformat()
    while True:
        last = calendar.monthrange(day.year, day.month)[1]
        candidate = day.replace(day=min(month_day or last, last))
        if candidate >= day:
            return candidate.isoformat()
        day = (day.replace(day=last) + timedelta(days=1))


def occurrence_deadline(rule, occurrence):
    if rule['due_on_planned']:
        return occurrence
    due_day = rule.get('due_day', -1)
    if due_day == -1 or rule['frequency'] == 'daily':
        return ''
    if rule['frequency'] == 'weekly':
        day = date.fromisoformat(occurrence)
        return (day + timedelta(days=(due_day - day.weekday()) % 7)).isoformat()
    return next_occurrence('monthly', [], due_day, occurrence, occurrence)


def cycle_start(frequency, day):
    day = date.fromisoformat(day)
    if frequency == 'weekly':
        day -= timedelta(days=day.weekday())
    elif frequency == 'monthly':
        day = day.replace(day=1)
    return day.isoformat()


def cycle_end(frequency, day):
    day = date.fromisoformat(day)
    if frequency == 'weekly':
        day += timedelta(days=6 - day.weekday())
    elif frequency == 'monthly':
        day = day.replace(day=calendar.monthrange(day.year, day.month)[1])
    return day.isoformat()


def sync_recurring(db, day, stamp):
    """Make the current cycle available early; never refill today's saved plan."""
    before = db.total_changes
    for row in db.execute("SELECT * FROM recurrences WHERE status='active'").fetchall():
        rule = dict(row)
        if rule['start_date'] > day:
            continue
        occurrence = rule['next_date']
        weekdays = json.loads(rule['weekdays'])
        horizon = cycle_end(rule['frequency'], day)
        while occurrence <= horizon:
            due = occurrence_deadline(rule, occurrence)
            end = cycle_end(rule['frequency'], occurrence)
            missed = rule['missed_policy'] == 'skip' and (due or end) < day
            db.execute('''INSERT OR IGNORE INTO tasks
                (id,title,due_date,consequence,energy,remaining_minutes,next_step,
                 status,created_at,updated_at,planned_date,recurrence_id,occurrence_date,missed_policy,missed,cycle_end)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (str(uuid4()), rule['title'], due,
                 rule['consequence'], rule['energy'], rule['minutes'], rule['next_step'],
                 'archived' if missed else 'active', stamp, stamp, occurrence, rule['id'],
                 occurrence, rule['missed_policy'], int(missed), end))
            after = (date.fromisoformat(occurrence) + timedelta(days=1)).isoformat()
            occurrence = next_occurrence(rule['frequency'], weekdays, rule['month_day'], cycle_start(rule['frequency'], rule['start_date']), after)
        if occurrence != rule['next_date']:
            db.execute('UPDATE recurrences SET next_date=? WHERE id=?', (occurrence, rule['id']))
    db.execute("""UPDATE tasks SET status='archived',missed=1,version=version+1,updated_at=?
        WHERE recurrence_id IS NOT NULL AND missed_policy='skip' AND status='active'
        AND planned_date<>'' AND COALESCE(NULLIF(due_date,''),MAX(cycle_end,planned_date))<?""", (stamp, day))
    return db.total_changes != before
