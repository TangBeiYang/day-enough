"""Daily capacity settings shared by planning, API and portable backups."""
import json
from datetime import date


def validate_capacity(weekly, overrides):
    if (not isinstance(weekly, list) or len(weekly) != 7 or
            any(value is not None and (type(value) is not int or not 0 <= value <= 960)
                for value in weekly)):
        raise ValueError('每周可用时间须是七天各自的 0–960 分钟，留空则采用默认值。')
    if not isinstance(overrides, dict) or len(overrides) > 366:
        raise ValueError('指定日期的可用时间最多设置 366 天。')
    for day, minutes in overrides.items():
        try:
            valid_day = (isinstance(day, str) and date.fromisoformat(day).isoformat() == day
                         and day <= '9998-12-31')
        except ValueError:
            valid_day = False
        if not valid_day or type(minutes) is not int or not 0 <= minutes <= 960:
            raise ValueError('指定日期和可用时间无效。')
    return weekly, overrides


def read_capacity(db):
    rows = dict(db.execute("SELECT key,value FROM meta WHERE key IN ('weekly_minutes','date_overrides')"))
    weekly = json.loads(rows.get('weekly_minutes', '[null,null,null,null,null,null,null]'))
    overrides = json.loads(rows.get('date_overrides', '{}'))
    return validate_capacity(weekly, overrides)


def minutes_on(day, default, weekly, overrides):
    key = day.isoformat()
    if key in overrides:
        return overrides[key]
    value = weekly[day.weekday()]
    return default if value is None else value
