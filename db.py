import sqlite3, os
from werkzeug.security import generate_password_hash
import config

PATH = os.path.join(config.DATA_DIR, "tutor.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS students(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id TEXT UNIQUE NOT NULL,
  email TEXT,
  name TEXT NOT NULL,
  batch TEXT NOT NULL,
  gender TEXT,
  pw_hash TEXT NOT NULL,
  status TEXT DEFAULT 'active',
  login_count INTEGER DEFAULT 0,
  last_login TEXT,
  is_demo INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS teachers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  pw_hash TEXT NOT NULL,
  is_admin INTEGER DEFAULT 0,
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS blocked(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pattern TEXT UNIQUE NOT NULL,
  reason TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS login_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_pk INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  at TEXT DEFAULT (datetime('now')),
  ip TEXT, ua TEXT
);
CREATE TABLE IF NOT EXISTS throttle(
  key TEXT PRIMARY KEY, fails INTEGER DEFAULT 0, locked_until REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_pk INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  course TEXT NOT NULL,
  question TEXT NOT NULL,
  answer TEXT,
  topic TEXT,
  in_scope INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS quiz(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_pk INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  course TEXT NOT NULL,
  qtype TEXT DEFAULT 'mcq',            -- mcq | theory | study
  topic TEXT,
  question TEXT NOT NULL,
  options TEXT,
  correct_idx INTEGER,
  explanation TEXT,
  model_answer TEXT,
  student_answer TEXT,
  score REAL,                          -- theory score 0-100
  feedback TEXT,
  chosen_idx INTEGER,
  is_correct INTEGER,                  -- NULL = not answered / study mode (not counted)
  created_at TEXT DEFAULT (datetime('now')),
  answered_at TEXT
);
CREATE TABLE IF NOT EXISTS recommendations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  course TEXT NOT NULL,
  text TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS feedback(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_pk INTEGER REFERENCES students(id) ON DELETE SET NULL,
  course TEXT,
  category TEXT DEFAULT 'general',
  message TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS custom_courses(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  code TEXT NOT NULL,
  program TEXT NOT NULL DEFAULT '',
  style TEXT NOT NULL DEFAULT '',
  intro_query TEXT NOT NULL DEFAULT 'course description objectives learning outcomes',
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_msg ON messages(course, student_pk);
CREATE INDEX IF NOT EXISTS ix_quiz ON quiz(course, student_pk);
CREATE INDEX IF NOT EXISTS ix_login ON login_events(student_pk);
"""

# columns added after the first version (so an older database upgrades itself)
MIGRATE = {
    "students": [("email", "TEXT"), ("status", "TEXT DEFAULT 'active'"), ("login_count", "INTEGER DEFAULT 0"), ("last_login", "TEXT")],
    "quiz": [("qtype", "TEXT DEFAULT 'mcq'"), ("model_answer", "TEXT"), ("student_answer", "TEXT"), ("score", "REAL"), ("feedback", "TEXT")],
    "teachers": [("is_admin", "INTEGER DEFAULT 0")],
}

def conn():
    c = sqlite3.connect(PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    if not config.IS_VERCEL:
        c.execute("PRAGMA journal_mode=WAL")
    return c

def init():
    with conn() as c:
        c.executescript(SCHEMA)
        for table, cols in MIGRATE.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for name, typ in cols:
                if name not in have: c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_email ON students(email) WHERE email IS NOT NULL")
        if not c.execute("SELECT 1 FROM teachers").fetchone():
            c.execute("INSERT INTO teachers(username,name,pw_hash,is_admin) VALUES(?,?,?,1)",
                      (config.TEACHER_USERNAME.lower(), config.INSTRUCTOR_NAME, generate_password_hash(config.TEACHER_PASSWORD)))
        # Ensure first teacher is admin
        c.execute("UPDATE teachers SET is_admin=1 WHERE id=(SELECT MIN(id) FROM teachers) AND is_admin=0")

def q(sql, args=(), one=False):
    with conn() as c:
        rows = c.execute(sql, args).fetchall()
    return (rows[0] if rows else None) if one else rows

def x(sql, args=()):
    with conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid
