# DayEnough

[中文说明](README_ch.md)

A personal task planner that helps you decide what to work on today—and how much is enough—based on deadlines, available time, and energy.

DayEnough is a desktop-first personal web app. It stores data on one server so the same tasks and progress are available across computers and operating systems.

## Features

- Username and password login, invite-code registration, and separate data for each account.
- Create, edit, complete, temporarily set aside, resume, and delete tasks.
- Optional deadlines for open-ended personal tasks.
- Optional planned dates for ordinary tasks; daily, weekly, and monthly recurring tasks with independent progress for each occurrence.
- Track estimated remaining time and actual time spent.
- Generate a daily plan from deadlines, planned dates, Stage goals, future recurring work, available time, and current energy.
- Arrange today's tasks yourself, set minutes and order, and save even when the total exceeds your budget after a clear warning.
- Record partial progress, complete a daily share, skip an item, reorder the plan, or explicitly regenerate it.
- Keep the daily plan stable: completing work never adds more tasks automatically.
- Protect data against stale cross-device edits and duplicate submissions.
- Export and restore JSON data, and make consistent online SQLite backups.
- Review ordinary tasks, current recurring occurrences, and recurrence rules together in Task overview.
- Create multi-day Stage plans for a weekend or holiday, track completion or time goals, and keep unfinished goals visible after the dates pass.

The app uses Python 3.11+, Flask, SQLite, and plain HTML, CSS, and JavaScript. It has no frontend build step and does not depend on external fonts, an AI API, or a CDN. Production deployment uses Linux and Gunicorn.

## Run locally

From the repository root on Linux or macOS (use WSL on Windows):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/flask --app day_enough set-password
.venv/bin/flask --app day_enough set-invite-code
.venv/bin/flask --app day_enough run --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. `set-password` sets the password for `owner`, which keeps all existing personal tasks; sign in with `owner` and your previous password. `set-invite-code` sets a registration code of at least 12 characters. New users need this code to register. Neither secret is stored in source code; registration is disabled until a code is set.

Run `set-password --username NAME` to reset an account password (`owner` by default). Its existing sessions are invalidated while task data remains intact. Run `set-invite-code` again to rotate the code, or `disable-registration` to pause new registrations.

The Flask development server is intended only for local use.

## Deploy on an Alibaba Cloud Linux server

Run the app with Gunicorn under a dedicated non-root user, bound only to `127.0.0.1:8000`. Put Caddy or an existing Nginx installation in front for public HTTPS. Keep SQLite data in a separate directory on the server; the same account sees its data from different devices. The included one-worker, two-thread service is a starting point for a personal 2-core, 2 GB server.

Before deploying, check the Linux distribution and Python version, existing sites or reverse proxies, domain and DNS. If you already have tasks locally, export a JSON backup from **Settings**. Do not expose the Flask development server or Gunicorn's port 8000 directly to the internet.

1. Install Python 3.11+, `venv`, and Git on the server; obtain the repository, create the service user and data directory, and install `requirements.lock`.
2. Set the personal password interactively, install the included systemd unit, and check the app locally on the server with `curl http://127.0.0.1:8000/`.
3. Point a domain at the server and configure Caddy, or reuse Nginx, to proxy to `127.0.0.1:8000`. Allow the required ports 80/443 in the Alibaba Cloud security group and host firewall, then verify HTTPS login. Port 8000 does not need to be public.
4. To migrate local tasks, sign in to the server-hosted site and restore the exported JSON from **Settings**. Sign in from another device to check synchronization, then configure backups.

The [full Linux deployment guide](docs/DEPLOYMENT.md) has commands, guidance for servers with existing sites, a temporary SSH tunnel when you have no domain yet, and backup and update steps. Inspect an existing proxy configuration before changing it.

## Which requirements file?

| File | Purpose |
| --- | --- |
| `requirements.txt` | Compatible version ranges for Flask and Gunicorn, used when maintaining dependencies. |
| `requirements.lock` | Pinned, tested production dependencies, including transitive packages; install this for local use and server deployment. |
| `requirements-dev.txt` | Includes `requirements.txt` plus pytest for development and backend tests. |
| `requirements-browser.txt` | Includes the development dependencies plus Playwright for optional browser acceptance tests; Chrome is installed separately. |

The running server only needs `requirements.lock`; test dependencies and Node are unnecessary.

## Daily workflow

1. Add a task and estimate how many minutes remain. A deadline is optional; open-ended projects can be left undated.
2. Set today's available time and energy, then generate a plan or choose **Arrange it myself** to select tasks, minutes, and order.
3. Use **Record part** for partial work or **Complete today's share** when the suggested share is done.
4. Correct the remaining-time estimate from the task list when reality differs.
5. Stop when today's shares are handled. New or edited tasks do not expand the plan until you explicitly regenerate it.

Filled deadlines use the end of that date in the `Asia/Shanghai` timezone. Undated tasks can still be recommended, but they do not produce deadline-risk warnings. Energy is a rough limit on high-effort work rather than a medical or physiological measure.

Regenerating a plan accounts for time already recorded and preserves completed or skipped shares. Skipping applies only to the current day. In **Settings**, set a default time budget, optional budgets for each weekday, and overrides for specific dates. The planner previews up to 60 future days in memory and saves only today’s suggested shares. Future energy is estimated as medium. Deadline and Stage shortfalls are estimates, not guarantees.

Manual planning keeps recorded work and handled shares. It warns when recorded work plus remaining scheduled minutes exceeds today's budget, but you can still save. The automatic planner continues to respect its time and energy limits.

## Planned dates and recurring tasks

A planned completion date means “I hope to finish this task on this day.” Tasks enter the recommendation pool as soon as they are created; approaching or missed targets increase priority. A deadline means “finish by this day.” Ordinary tasks can leave either date blank; a planned date cannot be later than a filled deadline.

Choose **Recurring task** to open its dedicated form: frequency, target completion weekdays or monthly date, optional deadline, start date, and minutes per occurrence. Weekly deadlines use weekdays; monthly deadlines use dates or month-end. Each occurrence uses the nearest matching deadline on or after its planned day, rolling into the next week/month when necessary. Dates such as the 31st fall on the last day of shorter months. A live summary explains the rule; energy, consequences, next steps, and the daily same-day deadline option are under **More settings**.

When you open or refresh the app or perform an action, daily occurrences are created for today, weekly occurrences for the current Monday–Sunday week, and monthly occurrences for the current month. All created occurrences can be recommended immediately. Completing one does not generate the next cycle early; no background scheduler is required. An explicitly future rule start date remains its activation date. Each has its own progress. By default, unfinished occurrences are marked missed after their deadline (or the end of their day/week/month if no deadline is set), retaining work already recorded without adding debt to the next occurrence. Choose **Keep pending** to keep unfinished occurrences available instead.

Manage rules and occurrence history in **Task overview → Recurrence rules and history**. Editing a rule affects future, uncreated occurrences; edit an existing occurrence separately. Pausing stops new occurrences but keeps existing ones. Resuming does not backfill the paused period. Recurring tasks still respect time and energy limits, and existing daily plans change only when explicitly regenerated.

Task overview shows active ordinary tasks, current recurring occurrences, any older occurrences still pending, and recurrence rule controls. “Set aside for now” keeps a task's progress for later. Deleting a task requires typing a confirmation and also removes its work logs and saved plan entries. Deleting one recurring occurrence leaves its rule and other occurrences intact and prevents that occurrence from returning on refresh. Deleting a whole rule removes all its occurrences and history; pause the rule if you want to keep that history.

## Stage plans

Open **Stage plans** in the sidebar to set a date range for a weekend, holiday, or other short stretch. Add existing tasks or create an ordinary task inside the plan. Each goal can mean completing the task or spending a chosen number of minutes from the plan's start date onward. The detail page shares the original task's progress and editing controls. Removing a goal or deleting a Stage plan keeps its tasks and work logs.

After the end date, unfinished goals stay in the plan and appear as a reminder on Today. Later work continues to count toward the goal. You can edit the plan, stop reminders by ending tracking, or resume tracking. A recurring occurrence set to **Skip missed work** cannot be added as a carry-over goal; use a task that keeps missed work pending instead. Stage goals affect automatic suggestions when you generate or regenerate today’s plan. Overdue goals stay eligible without gaining unlimited priority. On **Today**, choose **Arrange it myself** to filter for a Stage plan's tasks; filtering keeps any shares already selected. The current rules and forecast limits are documented in [Algorithm requirements](docs/ALGORITHM_REQUIREMENTS.md).

## Data and backups

By default, the `instance/` directory contains the SQLite database and session-signing key. It is excluded from Git. Set `DAY_ENOUGH_DATA` to use another absolute data directory.

- Use **Settings → Export JSON backup** for routine portable backups of the current account. The file contains tasks, recurrence rules, plans, work logs, and time budgets, but no password.
- Use **Settings → Restore from backup** to replace the current account's task data. Export its current state first.
- Make a consistent server-side SQLite backup with:

```bash
.venv/bin/flask --app day_enough backup backups/day-enough-2026-09-21.zip
```

The backup command uses SQLite's backup API, refuses to overwrite an existing file, and verifies database integrity. The ZIP includes the main database and every user database. Do not copy only the live main file. A complete backup contains password and invite-code hashes, so protect it like task data. A legacy single-user installation can still use a `.sqlite` backup, but multiple accounts require `.zip`. Stop the service before restoring the archive's `day-enough.sqlite` and `users/` directory together; see the [deployment guide](docs/DEPLOYMENT.md).

On startup, an existing database gains an account registry; its tasks, plans, progress, and settings remain under `owner`. Back up before upgrading and restart the app after updating the code. JSON exports remain at version 7; version 1–6 backups can still be restored, with the previous single daily default applied to all weekdays. Older app versions do not support multi-account data.

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
