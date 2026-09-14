PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO meta VALUES ('revision','0'),('default_minutes','120'),('auth_version','0');
CREATE TABLE IF NOT EXISTS tasks (
 id TEXT PRIMARY KEY,
 title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
 due_date TEXT NOT NULL,
 consequence TEXT NOT NULL CHECK(consequence IN ('low','medium','high')),
 energy TEXT NOT NULL CHECK(energy IN ('low','medium','high')),
 remaining_minutes INTEGER NOT NULL CHECK(remaining_minutes BETWEEN 0 AND 600000),
 worked_minutes INTEGER NOT NULL DEFAULT 0 CHECK(worked_minutes >= 0),
 next_step TEXT NOT NULL DEFAULT '' CHECK(length(next_step)<=500),
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','done','archived')),
 version INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
 day TEXT PRIMARY KEY,
 budget INTEGER NOT NULL CHECK(budget BETWEEN 0 AND 960),
 energy TEXT NOT NULL CHECK(energy IN ('low','medium','high')),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
 id TEXT PRIMARY KEY,
 day TEXT NOT NULL REFERENCES plans(day),
 task_id TEXT NOT NULL REFERENCES tasks(id),
 planned_minutes INTEGER NOT NULL CHECK(planned_minutes>0),
 done_minutes INTEGER NOT NULL DEFAULT 0 CHECK(done_minutes>=0),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','done','skipped')),
 reason TEXT NOT NULL,
 position INTEGER NOT NULL,
 UNIQUE(day,task_id)
);
CREATE TABLE IF NOT EXISTS work_logs (
 id TEXT PRIMARY KEY,
 task_id TEXT NOT NULL REFERENCES tasks(id),
 day TEXT NOT NULL,
 minutes INTEGER NOT NULL CHECK(minutes BETWEEN 1 AND 960),
 energy TEXT NOT NULL CHECK(energy IN ('low','medium','high')),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts (ip TEXT NOT NULL, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS work_day ON work_logs(day);
