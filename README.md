# DayEnough

[中文说明](README_ch.md)

A personal task planner that helps you decide what to work on today—and how much is enough—based on deadlines, available time, and energy.

DayEnough is a desktop-first personal web app. It stores data on one server so the same tasks and progress are available across computers and operating systems.

## Features

- Personal password login without registration or third-party accounts.
- Create, edit, complete, temporarily set aside, resume, and delete tasks.
- Optional deadlines for open-ended personal tasks.
- Optional planned dates for ordinary tasks; daily, weekly, and monthly recurring tasks with independent progress for each occurrence.
- Track estimated remaining time and actual time spent.
- Generate a daily plan from deadlines, consequences, remaining effort, available time, and current energy.
- Record partial progress, complete a daily share, skip an item, reorder the plan, or explicitly regenerate it.
- Keep the daily plan stable: completing work never adds more tasks automatically.
- Protect data against stale cross-device edits and duplicate submissions.
- Export and restore JSON data, and make consistent online SQLite backups.
- Review ordinary tasks, current recurring occurrences, and recurrence rules together in Task overview.

The app uses Python 3.11+, Flask, SQLite, and plain HTML, CSS, and JavaScript. It has no frontend build step and does not depend on external fonts, an AI API, or a CDN. Production deployment uses Linux and Gunicorn.

## Run locally

From the repository root on Linux or macOS (use WSL on Windows):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/flask --app day_enough set-password
.venv/bin/flask --app day_enough run --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. The password command initializes a personal password of at least 12 characters without storing it in source code. Until a password is configured, the app shows an initialization notice.

Run `set-password` again if the password is forgotten. Existing sessions will be invalidated while task data remains intact.

The Flask development server is intended only for local use. See the [deployment guide](docs/DEPLOYMENT.md) for a server setup.

## Daily workflow

1. Add a task and estimate how many minutes remain. A deadline is optional; open-ended projects can be left undated.
2. Set today's available time and energy, then generate a plan.
3. Use **Record part** for partial work or **Complete today's share** when the suggested share is done.
4. Correct the remaining-time estimate from the task list when reality differs.
5. Stop when today's shares are handled. New or edited tasks do not expand the plan until you explicitly regenerate it.

Filled deadlines use the end of that date in the `Asia/Shanghai` timezone. Undated tasks can still be recommended, but they do not produce deadline-risk warnings. Energy is a rough limit on high-effort work rather than a medical or physiological measure.

Regenerating a plan accounts for time already recorded and preserves completed or skipped shares. Skipping applies only to the current day. Future capacity currently assumes the same default available time every day, including weekends, and medium energy. Deadline warnings are estimates, not guarantees.

## Planned dates and recurring tasks

A planned completion date means “I hope to finish this task on this day.” Tasks enter the recommendation pool as soon as they are created; approaching or missed targets increase priority. A deadline means “finish by this day.” Ordinary tasks can leave either date blank; a planned date cannot be later than a filled deadline.

Choose **Recurring task** to open its dedicated form: frequency, target completion weekdays or monthly date, optional deadline, start date, and minutes per occurrence. Weekly deadlines use weekdays; monthly deadlines use dates or month-end. Each occurrence uses the nearest matching deadline on or after its planned day, rolling into the next week/month when necessary. Dates such as the 31st fall on the last day of shorter months. A live summary explains the rule; energy, consequences, next steps, and the daily same-day deadline option are under **More settings**.

When you open or refresh the app or perform an action, daily occurrences are created for today, weekly occurrences for the current Monday–Sunday week, and monthly occurrences for the current month. All created occurrences can be recommended immediately. Completing one does not generate the next cycle early; no background scheduler is required. An explicitly future rule start date remains its activation date. Each has its own progress. By default, unfinished occurrences are marked missed after their deadline (or the end of their day/week/month if no deadline is set), retaining work already recorded without adding debt to the next occurrence. Choose **Keep pending** to keep unfinished occurrences available instead.

Manage rules and occurrence history in **Task overview → Recurrence rules and history**. Editing a rule affects future, uncreated occurrences; edit an existing occurrence separately. Pausing stops new occurrences but keeps existing ones. Resuming does not backfill the paused period. Recurring tasks still respect time and energy limits, and existing daily plans change only when explicitly regenerated.

Task overview shows active ordinary tasks, current recurring occurrences, any older occurrences still pending, and recurrence rule controls. “Set aside for now” keeps a task's progress for later. Deleting a task requires typing a confirmation and also removes its work logs and saved plan entries. Deleting one recurring occurrence leaves its rule and other occurrences intact and prevents that occurrence from returning on refresh. Deleting a whole rule removes all its occurrences and history; pause the rule if you want to keep that history.

## Data and backups

By default, the `instance/` directory contains the SQLite database and session-signing key. It is excluded from Git. Set `DAY_ENOUGH_DATA` to use another absolute data directory.

- Use **Settings → Export JSON backup** for routine portable backups. The file contains tasks, recurrence rules, plans, work logs, and default time, but no password.
- Use **Settings → Restore from backup** to restore a JSON backup. This replaces all current task data, so export the current state first.
- Make a consistent server-side SQLite backup with:

```bash
.venv/bin/flask --app day_enough backup backups/day-enough-2026-09-21.sqlite
```

The backup command uses SQLite's backup API, refuses to overwrite an existing file, and verifies database integrity. Do not copy a live SQLite main file directly because unmerged data may still be in its WAL. A full SQLite backup includes the password hash and should be protected like the task data.

On startup, existing databases are automatically upgraded by adding the new fields and recurrence table. Back up before upgrading and restart the app after updating the code. JSON exports use version 5; version 1–4 backups can still be restored. Existing dates, progress, deadlines, and set-aside history are preserved. Dates act as completion targets; each occurrence stores its cycle end so later rule edits cannot change its expiry. Older app versions cannot read version 5 backups.

## Verification

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --check day_enough/static/app.js
```

Optional browser acceptance testing uses a temporary database and does not modify personal data:

```bash
.venv/bin/pip install -r requirements-browser.txt
.venv/bin/python tests/browser_smoke.py
```

The browser test uses `/usr/bin/google-chrome` by default. Set `CHROME_BIN` for another location. Screenshots are written to the ignored `test-results/` directory. Node is used only for the optional JavaScript syntax check; the app itself does not require Node.

## Project notes

- [MVP scope and rules](docs/MVP.md)
- [Features from the original proposal that are not implemented yet](docs/PLANNED_FEATURES.md)
- [Deployment guide](docs/DEPLOYMENT.md)
- [Development handoff status](docs/WORK_STATUS.md)
- [Original Chinese product proposal](raw/任务规划助手策划案v0.4.md)

Before continuing development in a new session, read `docs/WORK_STATUS.md` and `docs/MVP.md`. Update the status file after each verified milestone.

The current MVP does not include custom recurrence intervals, questionnaires, adaptive learning, a weekly view, AI reports, push notifications, offline synchronization, or multiple users. See the planned-features document for the complete comparison with the original proposal.
