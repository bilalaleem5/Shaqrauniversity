import sqlite3, os, re, logging, datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from werkzeug.security import generate_password_hash
import config

logger = logging.getLogger(__name__)

# Check if PostgreSQL / Neon is configured
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
IS_POSTGRES = bool(DATABASE_URL and ("postgres://" in DATABASE_URL or "postgresql://" in DATABASE_URL))

def _clean_pg_url(url):
    if not url: return None
    try:
        p = urlparse(url)
        qs = parse_qs(p.query)
        qs.pop("channel_binding", None)
        qs["sslmode"] = ["require"]
        return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(qs, doseq=True), p.fragment))
    except Exception:
        return url

CLEAN_DATABASE_URL = _clean_pg_url(DATABASE_URL) if IS_POSTGRES else None
PATH = os.path.join(config.DATA_DIR, "tutor.db")


SCHEMA_SQLITE = """
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
  sources TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS quiz(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_pk INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  course TEXT NOT NULL,
  qtype TEXT DEFAULT 'mcq',
  topic TEXT,
  question TEXT NOT NULL,
  options TEXT,
  correct_idx INTEGER,
  explanation TEXT,
  model_answer TEXT,
  student_answer TEXT,
  score REAL,
  feedback TEXT,
  chosen_idx INTEGER,
  is_correct INTEGER,
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

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS students(
  id SERIAL PRIMARY KEY,
  student_id TEXT UNIQUE NOT NULL,
  email TEXT,
  name TEXT NOT NULL,
  batch TEXT NOT NULL,
  gender TEXT,
  pw_hash TEXT NOT NULL,
  status TEXT DEFAULT 'active',
  login_count INTEGER DEFAULT 0,
  last_login TIMESTAMP,
  is_demo INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS teachers(
  id SERIAL PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  pw_hash TEXT NOT NULL,
  is_admin INTEGER DEFAULT 0,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS blocked(
  id SERIAL PRIMARY KEY,
  pattern TEXT UNIQUE NOT NULL,
  reason TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS login_events(
  id SERIAL PRIMARY KEY,
  student_pk INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  ip TEXT, ua TEXT
);
CREATE TABLE IF NOT EXISTS throttle(
  key TEXT PRIMARY KEY, fails INTEGER DEFAULT 0, locked_until DOUBLE PRECISION DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages(
  id SERIAL PRIMARY KEY,
  student_pk INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  course TEXT NOT NULL,
  question TEXT NOT NULL,
  answer TEXT,
  topic TEXT,
  in_scope INTEGER DEFAULT 1,
  sources TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS quiz(
  id SERIAL PRIMARY KEY,
  student_pk INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  course TEXT NOT NULL,
  qtype TEXT DEFAULT 'mcq',
  topic TEXT,
  question TEXT NOT NULL,
  options TEXT,
  correct_idx INTEGER,
  explanation TEXT,
  model_answer TEXT,
  student_answer TEXT,
  score DOUBLE PRECISION,
  feedback TEXT,
  chosen_idx INTEGER,
  is_correct INTEGER,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  answered_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS recommendations(
  id SERIAL PRIMARY KEY,
  course TEXT NOT NULL,
  text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS feedback(
  id SERIAL PRIMARY KEY,
  student_pk INTEGER REFERENCES students(id) ON DELETE SET NULL,
  course TEXT,
  category TEXT DEFAULT 'general',
  message TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS custom_courses(
  id SERIAL PRIMARY KEY,
  key TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  code TEXT NOT NULL,
  program TEXT NOT NULL DEFAULT '',
  style TEXT NOT NULL DEFAULT '',
  intro_query TEXT NOT NULL DEFAULT 'course description objectives learning outcomes',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_msg ON messages(course, student_pk);
CREATE INDEX IF NOT EXISTS ix_quiz ON quiz(course, student_pk);
CREATE INDEX IF NOT EXISTS ix_login ON login_events(student_pk);
"""

MIGRATE = {
    "students": [("email", "TEXT"), ("status", "TEXT DEFAULT 'active'"), ("login_count", "INTEGER DEFAULT 0"), ("last_login", "TEXT")],
    "quiz": [("qtype", "TEXT DEFAULT 'mcq'"), ("model_answer", "TEXT"), ("student_answer", "TEXT"), ("score", "REAL"), ("feedback", "TEXT")],
    "teachers": [("is_admin", "INTEGER DEFAULT 0")],
    "messages": [("sources", "TEXT")],
}

def _get_pg_conn():
    import psycopg2, psycopg2.extras
    conn = psycopg2.connect(CLEAN_DATABASE_URL)
    conn.autocommit = True
    return conn

def conn():
    if IS_POSTGRES:
        return _get_pg_conn()
    c = sqlite3.connect(PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    if not config.IS_VERCEL:
        c.execute("PRAGMA journal_mode=WAL")
    return c

def _translate_sql(sql):
    """Translate SQLite queries to PostgreSQL syntax."""
    if not IS_POSTGRES:
        return sql
    # Replace ? placeholders with %s
    sql_pg = sql.replace("?", "%s")
    # Replace SQLite datetime/date functions
    sql_pg = re.sub(r"datetime\('now'\)", "CURRENT_TIMESTAMP", sql_pg, flags=re.IGNORECASE)
    sql_pg = re.sub(r"date\('now'\)", "CURRENT_DATE", sql_pg, flags=re.IGNORECASE)
    return sql_pg

def init():
    if IS_POSTGRES:
        try:
            import psycopg2.extras
            c = _get_pg_conn()
            try:
                with c.cursor() as cur:
                    cur.execute(SCHEMA_PG)
                    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_email ON students(email) WHERE email IS NOT NULL")
                    cur.execute("SELECT 1 FROM teachers LIMIT 1")
                    if not cur.fetchone():
                        cur.execute(
                            "INSERT INTO teachers(username, name, pw_hash, is_admin) VALUES(%s, %s, %s, 1)",
                            (config.TEACHER_USERNAME.lower(), config.INSTRUCTOR_NAME, generate_password_hash(config.TEACHER_PASSWORD))
                        )
                    cur.execute("UPDATE teachers SET is_admin=1 WHERE id=(SELECT MIN(id) FROM teachers) AND is_admin=0")
            finally:
                c.close()
            logger.info("Neon PostgreSQL initialized successfully!")
            return
        except Exception as e:
            logger.error(f"Postgres init failed: {e}")
            raise

    # SQLite initialization
    with conn() as c:
        c.executescript(SCHEMA_SQLITE)
        for table, cols in MIGRATE.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for name, typ in cols:
                if name not in have: c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_email ON students(email) WHERE email IS NOT NULL")
        if not c.execute("SELECT 1 FROM teachers").fetchone():
            c.execute("INSERT INTO teachers(username,name,pw_hash,is_admin) VALUES(?,?,?,1)",
                      (config.TEACHER_USERNAME.lower(), config.INSTRUCTOR_NAME, generate_password_hash(config.TEACHER_PASSWORD)))
        c.execute("UPDATE teachers SET is_admin=1 WHERE id=(SELECT MIN(id) FROM teachers) AND is_admin=0")

class RowDict(dict):
    """Row object that supports dictionary keys, attribute access, and integer indexing."""
    def __init__(self, data=None, keys=None):
        super().__init__(data or {})
        self._keys = list(keys) if keys is not None else list(self.keys())

    def __getitem__(self, item):
        if isinstance(item, int):
            return super().__getitem__(self._keys[item])
        return super().__getitem__(item)

    def __getattr__(self, name):
        if name in self:
            return self[name]
        raise AttributeError(f"'RowDict' object has no attribute '{name}'")

def _clean_val(v):
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, datetime.date):
        return v.strftime("%Y-%m-%d")
    return v

def _wrap_row(r, keys):
    if r is None:
        return None
    d = {k: _clean_val(r[k]) for k in keys}
    return RowDict(d, keys)

def q(sql, args=(), one=False):
    sql_pg = _translate_sql(sql)
    if IS_POSTGRES:
        import psycopg2.extras
        c = _get_pg_conn()
        try:
            with c.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(sql_pg, args)
                rows = cur.fetchall()
                if not rows:
                    return None if one else []
                keys = [desc[0] for desc in cur.description]
                clean_rows = [_wrap_row(r, keys) for r in rows]
                return clean_rows[0] if one else clean_rows
        finally:
            c.close()

    with conn() as c:
        cur = c.execute(sql, args)
        rows = cur.fetchall()
        if not rows:
            return None if one else []
        keys = [desc[0] for desc in cur.description] if cur.description else []
        clean_rows = [_wrap_row(r, keys) for r in rows]
        return clean_rows[0] if one else clean_rows

def x(sql, args=()):
    sql_pg = _translate_sql(sql)
    if IS_POSTGRES:
        import psycopg2.extras
        is_insert = bool(re.match(r"^\s*INSERT\s+INTO", sql_pg, re.IGNORECASE))
        has_returning = "RETURNING" in sql_pg.upper()
        if is_insert and not has_returning:
            sql_pg = sql_pg.rstrip(" ;") + " RETURNING id"

        c = _get_pg_conn()
        try:
            with c.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(sql_pg, args)
                if is_insert:
                    try:
                        res = cur.fetchone()
                        return res[0] if res else cur.rowcount
                    except Exception:
                        return cur.rowcount
                return cur.rowcount
        finally:
            c.close()

    with conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid
