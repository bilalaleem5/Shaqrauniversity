import os, csv, io, time, json, secrets, hmac, random, string, threading, re
from collections import defaultdict, deque
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for, session, jsonify, abort, Response, flash, g, send_file)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
import config, db, rag, analytics, report, validators as V, study_guide, account_store

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.secret_key = config.SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 7,  # 7-day persistent session
    MAX_CONTENT_LENGTH=50 * 1024 * 1024  # 50 MB for uploads
)
db.init()
if config.OPENAI_API_KEY and not config.MOCK_LLM and not os.environ.get("NO_EMBED_THREAD") and not config.IS_VERCEL:
    threading.Thread(target=rag.ensure_embeddings, daemon=True).start()

BATCHES = ["2024", "2025", "2026"]
ALLOWED_UPLOAD = {".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md", ".pptx"}
_hits = defaultdict(deque)
MAX_FAILS, LOCK_SECONDS = 5, 600

# ------------------------------------------------------------------ helpers
def rate_ok(key, limit=40, window=3600):
    now = time.time(); d = _hits[key]
    while d and now - d[0] > window: d.popleft()
    if len(d) >= limit: return False
    d.append(now); return True

def ip(): return request.remote_addr or "?"

def throttled(key):
    r = db.q("SELECT * FROM throttle WHERE key=?", (key,), one=True)
    return bool(r and r["locked_until"] > time.time())

def fail(key):
    r = db.q("SELECT * FROM throttle WHERE key=?", (key,), one=True)
    n = (r["fails"] if r else 0) + 1
    lock = time.time() + LOCK_SECONDS if n >= MAX_FAILS else 0
    db.x("INSERT INTO throttle(key,fails,locked_until) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET fails=?, locked_until=?",
         (key, n % MAX_FAILS if lock else n, lock, n % MAX_FAILS if lock else n, lock))

def ok_login(key): db.x("DELETE FROM throttle WHERE key=?", (key,))

def blocked_patterns(): return [r["pattern"] for r in db.q("SELECT pattern FROM blocked")]

def csrf_token():
    if "csrf" not in session: session["csrf"] = secrets.token_hex(16)
    return session["csrf"]

def _all_courses():
    """Always get the full merged course list (static + DB custom)."""
    return config.get_all_courses()

@app.before_request
def csrf_protect():
    if request.method == "POST":
        sent = request.form.get("csrf") or request.headers.get("X-CSRF") or ""
        if not sent or not hmac.compare_digest(sent, session.get("csrf", "")): abort(400, "Session expired. Please reload the page.")

@app.after_request
def headers(r):
    r.headers.setdefault("X-Content-Type-Options", "nosniff")
    r.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    if request.path.startswith(("/api", "/teacher", "/chat", "/courses")): r.headers["Cache-Control"] = "no-store"
    return r

def current_student():
    if "student" in g: return g.student
    s = None
    pk = session.get("pk")
    sid = session.get("student_id")
    email = session.get("email")

    if pk or sid or email:
        if pk:
            try: s = db.q("SELECT * FROM students WHERE id=?", (pk,), one=True)
            except Exception: s = None
        if not s and sid:
            try:
                s = db.q("SELECT * FROM students WHERE lower(student_id)=?", (str(sid).lower(),), one=True)
                if s: session["pk"] = s["id"]
            except Exception: s = None
        if not s and email:
            try:
                s = db.q("SELECT * FROM students WHERE lower(email)=?", (str(email).lower(),), one=True)
                if s:
                    session["pk"] = s["id"]
                    session["student_id"] = s["student_id"]
            except Exception: s = None

        # If student exists in signed session but not in this serverless instance SQLite:
        if not s:
            student_id_val = str(sid or f"S_{pk or 1001}")
            email_val = session.get("email") or f"{student_id_val}@su.edu.sa"
            name_val = session.get("name") or f"Student {student_id_val}"
            batch_val = session.get("batch") or "2024"
            gender_val = session.get("gender") or ""
            status_val = session.get("status", "active")
            demo_val = int(session.get("is_demo") or 0)
            pw_hash_val = session.get("pw_hash")
            if not pw_hash_val or pw_hash_val == "restored_session":
                v_stu = account_store.find_student_in_vault(request, student_id_val) or account_store.find_student_in_vault(request, email_val)
                if v_stu and v_stu.get("pw_hash"):
                    pw_hash_val = v_stu["pw_hash"]
                    session["pw_hash"] = pw_hash_val
            if not pw_hash_val:
                pw_hash_val = "restored_session"

            try:
                # Try inserting into local SQLite so foreign keys (messages, quiz) succeed
                db.x(
                    """INSERT INTO students(student_id, email, name, batch, gender, pw_hash, status, is_demo)
                       VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(student_id) DO UPDATE SET 
                         name=excluded.name, 
                         status=excluded.status,
                         pw_hash=CASE WHEN excluded.pw_hash != 'restored_session' THEN excluded.pw_hash ELSE students.pw_hash END""",
                    (
                        student_id_val,
                        email_val,
                        name_val,
                        batch_val,
                        gender_val,
                        pw_hash_val,
                        status_val,
                        demo_val
                    )
                )
                s = db.q("SELECT * FROM students WHERE lower(student_id)=?", (student_id_val.lower(),), one=True)
                if s: session["pk"] = s["id"]
            except Exception as ex:
                app.logger.warning(f"Could not restore student to local db: {ex}")
                try:
                    s = db.q("SELECT * FROM students WHERE lower(email)=?", (email_val.lower(),), one=True)
                    if s: session["pk"] = s["id"]
                except Exception:
                    pass

            if not s:
                s = {
                    "id": pk or 1,
                    "student_id": student_id_val,
                    "name": name_val,
                    "email": email_val,
                    "batch": batch_val,
                    "gender": gender_val,
                    "status": status_val,
                    "is_demo": demo_val
                }

        # Check account status & block list
        if s:
            s = dict(s)
            if s.get("status") != "active" or (s.get("email") and V.is_blocked(s["email"], blocked_patterns())):
                s = None
                session.clear()

    g.student = s
    return s

def current_teacher():
    pk = session.get("teacher")
    if not pk: return None
    t = None
    try: t = db.q("SELECT * FROM teachers WHERE id=?", (pk,), one=True)
    except Exception: pass
    if not t:
        tuser = session.get("teacher_user")
        if tuser:
            try:
                t = db.q("SELECT * FROM teachers WHERE lower(username)=?", (str(tuser).lower(),), one=True)
                if t: session["teacher"] = t["id"]
            except Exception: pass
    return t

@app.context_processor
def inject():
    logo = "logo.png" if os.path.exists(os.path.join(app.static_folder, "logo.png")) else "logo.svg"
    return dict(logo=logo, COURSES=_all_courses(), student=current_student(), csrf=csrf_token(), teacher=current_teacher())

def student_required(f):
    @wraps(f)
    def w(*a, **k):
        if not current_student():
            return (jsonify(error="login"), 401) if request.path.startswith("/api") else redirect(url_for("login"))
        return f(*a, **k)
    return w

def teacher_required(f):
    @wraps(f)
    def w(*a, **k):
        if not current_teacher(): return redirect(url_for("teacher_login"))
        return f(*a, **k)
    return w

def admin_required(f):
    """Only the super-admin teacher (is_admin=1) can access."""
    @wraps(f)
    def w(*a, **k):
        t = current_teacher()
        if not t: return redirect(url_for("teacher_login"))
        if not t["is_admin"]: flash("Only the administrator can access that page.", "err"); return redirect(url_for("dashboard"))
        return f(*a, **k)
    return w

def course_or_404(c):
    courses = _all_courses()
    if c not in courses: abort(404)
    return c

def start_student_session(s, resp=None):
    s = dict(s)
    session.permanent = True
    session["pk"] = s["id"]
    session["student_id"] = str(s.get("student_id") or "")
    session["name"] = s.get("name") or ""
    session["email"] = s.get("email") or ""
    session["batch"] = s.get("batch") or "2024"
    session["gender"] = s.get("gender") or ""
    session["status"] = s.get("status") or "active"
    session["is_demo"] = int(s.get("is_demo") or 0)
    session["role"] = "student"
    if s.get("pw_hash") and s.get("pw_hash") != "restored_session":
        session["pw_hash"] = s.get("pw_hash")

    # Update client device vault
    new_vault_token = account_store.add_student_to_vault(request, s)
    session["vault_token"] = new_vault_token

    # Sync to cloud KV if configured
    account_store.sync_to_cloud_kv(s)

    csrf_token()
    try:
        db.x("UPDATE students SET login_count=login_count+1, last_login=datetime('now') WHERE id=?", (s["id"],))
        db.x("INSERT INTO login_events(student_pk,ip,ua) VALUES(?,?,?)", (s["id"], ip(), (request.headers.get("User-Agent") or "")[:160]))
    except Exception:
        pass

    if resp is not None and new_vault_token:
        resp.set_cookie(
            account_store.VAULT_COOKIE_NAME,
            new_vault_token,
            max_age=account_store.VAULT_COOKIE_MAX_AGE,
            httponly=False,
            samesite="Lax",
            secure=bool(os.environ.get("COOKIE_SECURE", "0") == "1")
        )
    return new_vault_token

# ------------------------------------------------------------------ landing / role selection
@app.route("/")
def home():
    if current_student(): return redirect(url_for("courses"))
    if current_teacher(): return redirect(url_for("dashboard"))
    return render_template("landing.html")

@app.route("/healthz")
def healthz(): return "ok"

# ------------------------------------------------------------------ student auth
@app.route("/login", methods=["GET", "POST"])
def login():
    err = None
    if request.method == "POST":
        ident = request.form.get("identifier", "").strip().lower()
        password = request.form.get("password", "")
        key = f"s:{ip()}:{ident}"
        if throttled(key):
            err = "Too many failed attempts. Please wait 10 minutes and try again."
        else:
            # 1. Search in local SQLite
            s = db.q("SELECT * FROM students WHERE lower(student_id)=? OR lower(email)=?", (ident, ident), one=True)

            # 2. If not found in SQLite, check cloud KV
            if not s:
                kv_stu = account_store.sync_from_cloud_kv(ident)
                if kv_stu:
                    try:
                        db.x(
                            """INSERT INTO students(student_id, email, name, batch, gender, pw_hash, status, is_demo)
                               VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                               ON CONFLICT(student_id) DO UPDATE SET pw_hash=excluded.pw_hash, status=excluded.status""",
                            (
                                kv_stu["student_id"], kv_stu["email"], kv_stu["name"],
                                kv_stu.get("batch", "2024"), kv_stu.get("gender", ""),
                                kv_stu["pw_hash"], kv_stu.get("status", "active"), int(kv_stu.get("is_demo", 0))
                            )
                        )
                        s = db.q("SELECT * FROM students WHERE lower(student_id)=? OR lower(email)=?", (ident, ident), one=True)
                    except Exception as ex:
                        app.logger.warning(f"KV restore failed: {ex}")

            # 3. If still not in SQLite, check client device vault!
            if not s:
                vault_stu = account_store.find_student_in_vault(request, ident)
                if vault_stu:
                    if check_password_hash(vault_stu["pw_hash"], password):
                        try:
                            db.x(
                                """INSERT INTO students(student_id, email, name, batch, gender, pw_hash, status, is_demo)
                                   VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                                   ON CONFLICT(student_id) DO UPDATE SET pw_hash=excluded.pw_hash, status=excluded.status""",
                                (
                                    vault_stu["student_id"], vault_stu["email"], vault_stu["name"],
                                    vault_stu.get("batch", "2024"), vault_stu.get("gender", ""),
                                    vault_stu["pw_hash"], vault_stu.get("status", "active"), int(vault_stu.get("is_demo", 0))
                                )
                            )
                            s = db.q("SELECT * FROM students WHERE lower(student_id)=? OR lower(email)=?", (vault_stu["student_id"].lower(), vault_stu["email"].lower()), one=True)
                        except Exception as ex:
                            app.logger.warning(f"Vault restore failed: {ex}")

            # 4. If s was found in SQLite but has dummy pw_hash 'restored_session':
            if s and s["pw_hash"] == "restored_session":
                vault_stu = account_store.find_student_in_vault(request, ident)
                if vault_stu and check_password_hash(vault_stu["pw_hash"], password):
                    db.x("UPDATE students SET pw_hash=? WHERE id=?", (vault_stu["pw_hash"], s["id"]))
                    s = db.q("SELECT * FROM students WHERE id=?", (s["id"],), one=True)

            # 5. Validate password and student status
            if s and check_password_hash(s["pw_hash"], password):
                if s["status"] != "active":
                    err = "This account is suspended. Please contact your instructor."
                elif V.is_blocked(s["email"], blocked_patterns()):
                    err = "This account is not allowed to use the system."
                else:
                    ok_login(key)
                    resp = redirect(url_for("courses"))
                    start_student_session(s, resp=resp)
                    return resp
            else:
                fail(key)
                err = "Wrong student ID / email or password."
    return render_template("login.html", mode="login", err=err, batches=BATCHES)

@app.route("/register", methods=["GET", "POST"])
def register():
    err = None
    if request.method == "POST":
        f = request.form
        name, sid = " ".join(f.get("name", "").split()), f.get("student_id", "").strip()
        email, batch, pw = V.norm_email(f.get("email")), f.get("batch", ""), f.get("password", "")
        gender = f.get("gender", "")
        err = V.check_registration(name, sid, email, batch, pw, BATCHES)
        if not err and pw != f.get("password2", ""): 
            err = "The two passwords do not match."
        if not err and V.is_blocked(email, blocked_patterns()): 
            err = "This email address is not allowed. Please contact your instructor."

        if not err and db.q("SELECT 1 FROM students WHERE lower(student_id)=?", (sid.lower(),), one=True):
            err = "This student ID is already registered. Please log in."
        if not err and db.q("SELECT 1 FROM students WHERE lower(email)=?", (email.lower(),), one=True):
            err = "This email is already registered. Please log in."

        # If not in local SQLite, check if existing in cloud KV or client device vault
        if not err:
            existing_vault = account_store.sync_from_cloud_kv(sid) or account_store.sync_from_cloud_kv(email)
            if not existing_vault:
                existing_vault = account_store.find_student_in_vault(request, sid) or account_store.find_student_in_vault(request, email)

            if existing_vault:
                # If student typed the matching password, auto-restore and sign them in!
                if existing_vault.get("pw_hash") and existing_vault["pw_hash"] != "restored_session" and check_password_hash(existing_vault["pw_hash"], pw):
                    try:
                        db.x(
                            """INSERT INTO students(student_id, email, name, batch, gender, pw_hash, status, is_demo)
                               VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                               ON CONFLICT(student_id) DO UPDATE SET pw_hash=excluded.pw_hash, name=excluded.name, status=excluded.status""",
                            (
                                existing_vault["student_id"], existing_vault["email"], existing_vault["name"],
                                existing_vault.get("batch", batch or "2024"), existing_vault.get("gender", gender or ""),
                                existing_vault["pw_hash"], existing_vault.get("status", "active"), int(existing_vault.get("is_demo", 0))
                            )
                        )
                        s = db.q("SELECT * FROM students WHERE lower(student_id)=?", (existing_vault["student_id"].lower(),), one=True)
                    except Exception:
                        s = existing_vault
                    resp = redirect(url_for("courses"))
                    start_student_session(s or existing_vault, resp=resp)
                    return resp
                else:
                    err = "This student ID or email is already registered. Please log in."

        if not err and not rate_ok(("reg", ip()), limit=15, window=3600): 
            err = "Too many sign-ups from this network. Try again later."

        if not err:
            gen_val = gender if gender in ("male", "female") else ""
            pw_hash = generate_password_hash(pw)
            pk = db.x("INSERT INTO students(student_id,email,name,batch,gender,pw_hash) VALUES(?,?,?,?,?,?)",
                      (sid, email, name, batch, gen_val, pw_hash))
            s_obj = {
                "id": pk,
                "student_id": sid,
                "name": name,
                "email": email,
                "batch": batch,
                "gender": gen_val,
                "pw_hash": pw_hash,
                "status": "active",
                "is_demo": 0
            }
            resp = redirect(url_for("courses"))
            start_student_session(s_obj, resp=resp)
            return resp

    return render_template("login.html", mode="register", err=err, batches=BATCHES)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# ------------------------------------------------------------------ student app
@app.route("/courses")
@student_required
def courses():
    guides = study_guide.get_all_guides()
    return render_template("courses.html", guides=guides)

@app.route("/guide/<course>")
@student_required
def guide(course):
    course_or_404(course)
    courses = _all_courses()
    g_data = study_guide.get_guide(course)
    if not g_data:
        abort(404, "Study guide not available for this course.")
    return render_template("guide.html", course=course, cfg=courses[course], guide=g_data, guide_items=g_data.get("items", []))

@app.route("/guide/<course>/download")
@student_required
def guide_download(course):
    course_or_404(course)
    fpath, fname = study_guide.get_guide_file_path(course)
    if not fpath or not os.path.exists(fpath):
        abort(404, "Study guide file not found.")
    return send_file(fpath, as_attachment=True, download_name=fname)

@app.route("/api/guide/<course>")
@student_required
def api_guide(course):
    course_or_404(course)
    g_data = study_guide.get_guide(course)
    if not g_data:
        return jsonify(error="Not found"), 404
    return jsonify(g_data)

@app.route("/chat/<course>")
@student_required
def chat(course):
    course_or_404(course)
    courses = _all_courses()
    g_data = study_guide.get_guide(course)
    prompt = request.args.get("prompt", "").strip()
    return render_template("chat.html", course=course, cfg=courses[course], topics=rag.topics(course), guide=g_data, initial_prompt=prompt)

@app.route("/api/chat/<course>", methods=["POST"])
@student_required
def api_chat(course):
    course_or_404(course); s = current_student(); d = request.get_json(force=True, silent=True) or {}
    intro = bool(d.get("intro")); text = str(d.get("message") or "").strip()[:1500]
    if intro: text = "Please introduce this course to me."
    if not text: return jsonify(error="Please type a question."), 400
    if not rate_ok(("chat", s["id"]), limit=60): return jsonify(error="You reached the hourly limit. Please try again later."), 429
    history = d.get("history") if isinstance(d.get("history"), list) else []
    try:
        r = rag.answer(course, text, [h for h in history if isinstance(h, dict)], intro=intro)
    except Exception as e:
        app.logger.exception(e); return jsonify(error="The tutor is temporarily unavailable. Please try again."), 502
    if not intro:
        try:
            db.x("INSERT INTO messages(student_pk,course,question,answer,topic,in_scope) VALUES(?,?,?,?,?,?)",
                 (s["id"], course, text, r["answer"], r["topic"], r["in_scope"]))
        except Exception as e:
            app.logger.warning(f"Could not save chat message: {e}")
    return jsonify(r)

def _pick_topic(course, topic):
    tl = rag.topics(course)
    if topic in tl: return topic
    good = [t for t in tl if "Specification" not in t and not t.startswith(("CS_", "TP-")) and "Action Plan" not in t]
    return random.choice(good or tl)

@app.route("/api/quiz/<course>/next", methods=["POST"])
@student_required
def quiz_next(course):
    course_or_404(course); s = current_student(); d = request.get_json(force=True, silent=True) or {}
    kind = d.get("kind") if d.get("kind") in ("mcq", "theory", "study") else "mcq"
    topic = _pick_topic(course, d.get("topic"))
    if not rate_ok(("quiz", s["id"]), limit=80): return jsonify(error="Hourly limit reached."), 429
    qtype = "mcq" if kind == "mcq" else ("theory" if kind == "theory" else "study")
    avoid = [r["question"] for r in db.q("SELECT question FROM quiz WHERE student_pk=? AND course=? AND topic=? AND qtype=? ORDER BY id DESC LIMIT 8",
                                         (s["id"], course, topic, qtype))]
    try:
        if kind == "mcq":
            qz = rag.make_question(course, topic, avoid)
            if not qz: raise ValueError("no question")
            qid = db.x("INSERT INTO quiz(student_pk,course,qtype,topic,question,options,correct_idx,explanation) VALUES(?,?,?,?,?,?,?,?)",
                       (s["id"], course, "mcq", topic, qz["question"], json.dumps(qz["options"], ensure_ascii=False), qz["correct_idx"], qz.get("explanation", "")))
            return jsonify(id=qid, kind="mcq", topic=topic, question=qz["question"], options=qz["options"])
        qz = rag.make_theory(course, topic, avoid)
        if not qz: raise ValueError("no question")
        qid = db.x("INSERT INTO quiz(student_pk,course,qtype,topic,question,model_answer) VALUES(?,?,?,?,?,?)",
                   (s["id"], course, qtype, topic, qz["question"], qz["model_answer"]))
        out = dict(id=qid, kind=kind, topic=topic, question=qz["question"])
        if kind == "study": out["model_answer"] = qz["model_answer"]       # with answer
        return jsonify(out)
    except Exception as e:
        app.logger.exception(e); return jsonify(error="Could not create a question, please try again."), 502

def _my_quiz(qid):
    s = current_student()
    return db.q("SELECT * FROM quiz WHERE id=? AND student_pk=?", (qid, s["id"]), one=True) or abort(404)

def _totals(course):
    r = db.q("SELECT COUNT(*) n, COALESCE(SUM(is_correct),0) ok FROM quiz WHERE student_pk=? AND course=? AND is_correct IS NOT NULL",
             (current_student()["id"], course), one=True)
    return r["n"], r["ok"]

@app.route("/api/quiz/answer", methods=["POST"])
@student_required
def quiz_answer():
    d = request.get_json(force=True, silent=True) or {}
    z = _my_quiz(d.get("id"))
    if z["qtype"] != "mcq": abort(400)
    if z["chosen_idx"] is not None: return jsonify(error="Already answered"), 400
    try: ch = int(d.get("chosen", -1))
    except (TypeError, ValueError): ch = -1
    if not 0 <= ch <= 3: return jsonify(error="Invalid choice"), 400
    ok = int(ch == z["correct_idx"])
    db.x("UPDATE quiz SET chosen_idx=?, is_correct=?, answered_at=datetime('now') WHERE id=?", (ch, ok, z["id"]))
    n, right = _totals(z["course"])
    return jsonify(correct=bool(ok), correct_idx=z["correct_idx"], explanation=z["explanation"], total=n, right=right)

@app.route("/api/quiz/theory", methods=["POST"])
@student_required
def quiz_theory():
    d = request.get_json(force=True, silent=True) or {}
    z = _my_quiz(d.get("id"))
    if z["qtype"] != "theory": abort(400)
    if z["answered_at"]: return jsonify(error="Already answered"), 400
    if d.get("reveal"):                                  # show answer without being graded
        db.x("UPDATE quiz SET answered_at=datetime('now'), feedback='revealed without answering' WHERE id=?", (z["id"],))
        return jsonify(model_answer=z["model_answer"], revealed=True)
    ans = str(d.get("answer") or "").strip()[:3000]
    if len(ans) < 5: return jsonify(error="Please write your answer first (at least a sentence)."), 400
    if not rate_ok(("grade", current_student()["id"]), limit=60): return jsonify(error="Hourly limit reached."), 429
    try: g_ = rag.grade_theory(z["question"], z["model_answer"], ans)
    except Exception as e:
        app.logger.exception(e); return jsonify(error="Grading is temporarily unavailable, please try again."), 502
    ok = int(g_["score"] >= 60)
    db.x("UPDATE quiz SET student_answer=?, score=?, feedback=?, is_correct=?, answered_at=datetime('now') WHERE id=?",
         (ans, g_["score"], g_["feedback"], ok, z["id"]))
    n, right = _totals(z["course"])
    return jsonify(score=g_["score"], feedback=g_["feedback"], model_answer=z["model_answer"], correct=bool(ok), total=n, right=right)

# ------------------------------------------------------------------ student feedback (anonymous)
@app.route("/feedback", methods=["GET", "POST"])
@student_required
def student_feedback():
    if request.method == "POST":
        msg = request.form.get("message", "").strip()[:2000]
        course = request.form.get("course", "")
        category = request.form.get("category", "general")
        if len(msg) < 5:
            flash("Please write at least a few words.", "err")
        else:
            db.x("INSERT INTO feedback(student_pk,course,category,message) VALUES(?,?,?,?)",
                 (current_student()["id"], course if course in _all_courses() else "", category, msg))
            flash("Thank you! Your anonymous feedback has been submitted to your instructor.", "ok")
            return redirect(url_for("student_feedback"))
    return render_template("feedback.html")

# ------------------------------------------------------------------ teacher auth + settings
@app.route("/instructor")
@app.route("/instructor/login")
def old_url(): return redirect(url_for("dashboard"))

@app.route("/teacher/login", methods=["GET", "POST"])
def teacher_login():
    err = None
    if request.method == "POST":
        u = request.form.get("username", "").strip().lower(); key = f"t:{ip()}:{u}"
        if throttled(key): err = "Too many failed attempts. Please wait 10 minutes."
        else:
            t = db.q("SELECT * FROM teachers WHERE username=?", (u,), one=True)
            if t and check_password_hash(t["pw_hash"], request.form.get("password", "")):
                ok_login(key); session.clear(); session.permanent = True
                session["teacher"] = t["id"]
                session["teacher_user"] = t["username"]
                session["teacher_name"] = t["name"]
                session["role"] = "teacher"
                return redirect(url_for("dashboard"))
            fail(key); err = "Wrong username or password."
    return render_template("t_login.html", err=err)

@app.route("/teacher/logout")
def teacher_logout():
    session.clear(); return redirect(url_for("home"))

@app.route("/teacher/settings", methods=["GET", "POST"])
@teacher_required
def settings():
    t = current_teacher()
    if request.method == "POST":
        f = request.form; kind = f.get("kind")
        if kind == "name":
            n = " ".join(f.get("name", "").split())[:60]
            if len(n) < 2: flash("Please enter a valid name.", "err")
            else: db.x("UPDATE teachers SET name=? WHERE id=?", (n, t["id"])); flash("Name updated.", "ok")
        else:
            if not check_password_hash(t["pw_hash"], f.get("current", "")): flash("Current password is wrong.", "err")
            elif V.check_password(f.get("new", "")): flash(V.check_password(f.get("new", "")), "err")
            elif f.get("new") != f.get("confirm"): flash("The new passwords do not match.", "err")
            elif f.get("new") == f.get("current"): flash("The new password must be different.", "err")
            else:
                db.x("UPDATE teachers SET pw_hash=?, updated_at=datetime('now') WHERE id=?", (generate_password_hash(f["new"]), t["id"]))
                flash("Password changed successfully.", "ok")
        return redirect(url_for("settings"))
    return render_template("t_settings.html", t=t, active="settings")

# ------------------------------------------------------------------ teacher: analytics
def _course_arg():
    courses = _all_courses()
    return course_or_404(request.args.get("course", next(iter(courses))))

def _latest_reco(course):
    return db.q("SELECT * FROM recommendations WHERE course=? ORDER BY id DESC LIMIT 1", (course,), one=True)

@app.route("/teacher")
@teacher_required
def dashboard():
    c = _course_arg(); st = analytics.compute(c)
    extra = db.q("SELECT (SELECT COUNT(*) FROM login_events WHERE date(at)=date('now')) today, (SELECT COUNT(*) FROM students WHERE status!='active') susp", one=True)
    return render_template("dashboard.html", course=c, cfg=_all_courses()[c], st=st, reco=_latest_reco(c), active="dash",
                           ai_live=rag._have_llm(), logins_today=extra["today"], suspended=extra["susp"])

@app.route("/teacher/recommend", methods=["POST"])
@teacher_required
def recommend():
    c = _course_arg(); st = analytics.compute(c)
    if not st["messages"] and not st["quiz_attempts"]:
        flash("No student activity yet, nothing to analyse.", "err"); return redirect(url_for("dashboard", course=c))
    try: text = rag.recommendations(c, analytics.anonymised(st))
    except Exception as e:
        app.logger.exception(e); flash("Could not generate recommendations right now. Please try again.", "err"); return redirect(url_for("dashboard", course=c))
    db.x("INSERT INTO recommendations(course,text) VALUES(?,?)", (c, text))
    return redirect(url_for("dashboard", course=c) + "#reco")

@app.route("/teacher/report.pdf")
@teacher_required
def report_pdf():
    c = _course_arg(); st = analytics.compute(c); r = _latest_reco(c)
    return Response(report.build(st, r["text"] if r else None), mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{c}_analytics_report.pdf"'})

@app.route("/teacher/export.csv")
@teacher_required
def export_csv():
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["student_id", "name", "email", "batch", "section", "registered", "last_login", "logins", "status",
                "questions_asked", "quiz_answers", "quiz_accuracy_pct"])
    for r in _students_rows():
        w.writerow([r["student_id"], r["name"], r["email"] or "", r["batch"], r["gender"] or "", r["created_at"], r["last_login"] or "",
                    r["login_count"], r["status"], r["msgs"], r["quizzes"], r["acc"] if r["acc"] is not None else ""])
    return Response("\ufeff" + out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": 'attachment; filename="students.csv"'})

# ------------------------------------------------------------------ teacher: user management
def _students_rows():
    return db.q("""SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.student_pk=s.id) msgs,
        (SELECT COUNT(*) FROM quiz z WHERE z.student_pk=s.id AND z.is_correct IS NOT NULL) quizzes,
        (SELECT ROUND(100.0*SUM(is_correct)/COUNT(*),0) FROM quiz z WHERE z.student_pk=s.id AND z.is_correct IS NOT NULL) acc
        FROM students s ORDER BY s.created_at DESC""")

@app.route("/teacher/students")
@teacher_required
def students_page():
    return render_template("t_students.html", rows=_students_rows(), active="students")

@app.route("/teacher/student/<int:pk>")
@teacher_required
def student_detail(pk):
    c = _course_arg(); base = db.q("SELECT * FROM students WHERE id=?", (pk,), one=True) or abort(404)
    st = analytics.compute(c); s = next((x for x in st["students"] if x["pk"] == pk), None)
    msgs = db.q("SELECT * FROM messages WHERE student_pk=? AND course=? ORDER BY id DESC LIMIT 60", (pk, c))
    theory = db.q("SELECT * FROM quiz WHERE student_pk=? AND course=? AND qtype='theory' AND answered_at IS NOT NULL ORDER BY id DESC LIMIT 15", (pk, c))
    logins = db.q("SELECT * FROM login_events WHERE student_pk=? ORDER BY id DESC LIMIT 15", (pk,))
    return render_template("t_student.html", course=c, cfg=_all_courses()[c], s=s, base=base, msgs=msgs, theory=theory, logins=logins, active="students")

def _temp_password():
    while True:
        p = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
        if not V.check_password(p): return p

@app.route("/teacher/student/<int:pk>/action", methods=["POST"])
@teacher_required
def student_action(pk):
    s = db.q("SELECT * FROM students WHERE id=?", (pk,), one=True) or abort(404)
    act = request.form.get("action"); back = url_for("students_page")
    if act == "suspend":
        db.x("UPDATE students SET status='suspended' WHERE id=?", (pk,)); flash(f"{s['name']} was suspended (cannot log in).", "ok")
    elif act == "activate":
        db.x("UPDATE students SET status='active' WHERE id=?", (pk,)); flash(f"{s['name']} was re-activated.", "ok")
    elif act == "reset_password":
        p = _temp_password(); db.x("UPDATE students SET pw_hash=? WHERE id=?", (generate_password_hash(p), pk))
        flash(f"New temporary password for {s['name']} ({s['student_id']}): {p}   (tell the student, shown only once)", "ok")
        back = url_for("student_detail", pk=pk)
    elif act in ("delete", "delete_block"):
        if act == "delete_block" and s["email"]:
            db.x("INSERT OR IGNORE INTO blocked(pattern,reason) VALUES(?,?)", (s["email"], f"removed student {s['student_id']}"))
        db.x("DELETE FROM students WHERE id=?", (pk,))
        flash(f"{s['name']} was deleted with all their data" + (" and the email was blocked." if act == "delete_block" else "."), "ok")
    elif act == "block_email" and s["email"]:
        db.x("INSERT OR IGNORE INTO blocked(pattern,reason) VALUES(?,?)", (s["email"], f"blocked student {s['student_id']}"))
        flash(f"{s['email']} is blocked. The student can no longer log in.", "ok"); back = url_for("student_detail", pk=pk)
    else: abort(400)
    return redirect(back)

@app.route("/teacher/blocked", methods=["GET", "POST"])
@teacher_required
def blocked_page():
    if request.method == "POST":
        p = V.block_pattern(request.form.get("pattern"))
        if not p: flash("Enter a valid email (name@example.com) or a domain (example.com).", "err")
        else:
            db.x("INSERT OR IGNORE INTO blocked(pattern,reason) VALUES(?,?)", (p, (request.form.get("reason") or "")[:120])); flash(f"{p} is now blocked.", "ok")
        return redirect(url_for("blocked_page"))
    return render_template("t_blocked.html", rows=db.q("SELECT * FROM blocked ORDER BY id DESC"), active="blocked")

@app.route("/teacher/blocked/<int:bid>/remove", methods=["POST"])
@teacher_required
def blocked_remove(bid):
    db.x("DELETE FROM blocked WHERE id=?", (bid,)); flash("Removed from the blocked list.", "ok")
    return redirect(url_for("blocked_page"))

# ------------------------------------------------------------------ teacher: question bank (with / without answers)
@app.route("/teacher/question-bank", methods=["GET", "POST"])
@teacher_required
def question_bank():
    courses = _all_courses()
    if request.method == "POST":
        f = request.form; c = course_or_404(f.get("course"))
        kind = f.get("kind") if f.get("kind") in ("mcq", "theory") else "mcq"
        try: n = max(1, min(20, int(f.get("count", 10))))
        except ValueError: n = 10
        tl = [t for t in f.getlist("topics") if t in rag.topics(c)] or [t for t in rag.topics(c) if "Specification" not in t and not t.startswith(("CS_", "TP-"))]
        try: items = rag.make_bank(c, tl, kind, n)
        except Exception as e:
            app.logger.exception(e); items = []
        if not items:
            flash("Could not generate questions right now. Please try again.", "err"); return redirect(url_for("question_bank"))
        with_ans = f.get("with_answers") == "1"
        pdf = report.question_sheet(courses[c], items, kind, with_ans)
        return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition":
                        f'attachment; filename="{c}_{kind}_{"with" if with_ans else "without"}_answers.pdf"'})
    return render_template("t_bank.html", topics={c: rag.topics(c) for c in courses}, active="bank")

# ------------------------------------------------------------------ teacher: knowledge base management
@app.route("/teacher/knowledge")
@teacher_required
def knowledge_base():
    courses = _all_courses()
    c = request.args.get("course", next(iter(courses)))
    if c not in courses: c = next(iter(courses))
    # List files in the knowledge folder for the selected course
    folder = courses[c]["folder"]
    files = []
    if os.path.isdir(folder):
        for fname in sorted(os.listdir(folder)):
            fpath = os.path.join(folder, fname)
            if os.path.isfile(fpath):
                ext = os.path.splitext(fname)[1].lower()
                sz = os.path.getsize(fpath)
                files.append({"name": fname, "ext": ext, "size_kb": round(sz / 1024, 1), "path": fpath})
    return render_template("t_knowledge.html", course=c, files=files, active="knowledge")

@app.route("/teacher/knowledge/upload", methods=["POST"])
@teacher_required
def knowledge_upload():
    courses = _all_courses()
    c = request.form.get("course", "")
    if c not in courses:
        flash("Invalid course.", "err"); return redirect(url_for("knowledge_base"))
    folder = courses[c]["folder"]
    os.makedirs(folder, exist_ok=True)
    uploaded = request.files.getlist("files")
    count = 0
    for f in uploaded:
        if not f or not f.filename: continue
        fname = secure_filename(f.filename)
        ext = os.path.splitext(fname)[1].lower()
        if ext not in ALLOWED_UPLOAD:
            flash(f"Skipped {fname}: unsupported file type ({ext}).", "err"); continue
        dest = os.path.join(folder, fname)
        f.save(dest)
        count += 1
    if count:
        # Rebuild chunk index for the course so new files are included
        try:
            rag.build_chunks(c)
            flash(f"Uploaded {count} file(s) and rebuilt the knowledge index for {courses[c]['title']}.", "ok")
            # Trigger embedding in background if OpenAI available
            if rag._have_llm():
                threading.Thread(target=_rebuild_embeddings, args=(c,), daemon=True).start()
        except Exception as e:
            app.logger.exception(e)
            flash(f"Uploaded {count} file(s) but index rebuild encountered an error. Try re-indexing manually.", "err")
    return redirect(url_for("knowledge_base", course=c))

def _rebuild_embeddings(course):
    try: rag.build_embeddings(course)
    except Exception as e: print(f"Embedding rebuild failed for {course}:", e)

@app.route("/teacher/knowledge/delete", methods=["POST"])
@teacher_required
def knowledge_delete():
    courses = _all_courses()
    c = request.form.get("course", "")
    fname = request.form.get("filename", "")
    if c not in courses or not fname:
        flash("Invalid request.", "err"); return redirect(url_for("knowledge_base"))
    folder = courses[c]["folder"]
    fpath = os.path.join(folder, secure_filename(fname))
    if os.path.isfile(fpath):
        os.remove(fpath)
        try: rag.build_chunks(c)
        except Exception: pass
        flash(f"Deleted {fname} and rebuilt index.", "ok")
    else:
        flash("File not found.", "err")
    return redirect(url_for("knowledge_base", course=c))

@app.route("/teacher/knowledge/reindex", methods=["POST"])
@teacher_required
def knowledge_reindex():
    courses = _all_courses()
    c = request.form.get("course", "")
    if c not in courses:
        flash("Invalid course.", "err"); return redirect(url_for("knowledge_base"))
    try:
        n = rag.build_chunks(c)
        flash(f"Re-indexed {courses[c]['title']}: {len(n)} text chunks created.", "ok")
        if rag._have_llm():
            threading.Thread(target=_rebuild_embeddings, args=(c,), daemon=True).start()
            flash("Embedding generation started in background.", "ok")
    except Exception as e:
        app.logger.exception(e)
        flash("Index rebuild failed. Check logs.", "err")
    return redirect(url_for("knowledge_base", course=c))

# ------------------------------------------------------------------ teacher: course management (admin only)
@app.route("/teacher/courses", methods=["GET", "POST"])
@admin_required
def manage_courses():
    if request.method == "POST":
        f = request.form
        title = " ".join(f.get("title", "").split())[:100]
        code = " ".join(f.get("code", "").split())[:30]
        program = " ".join(f.get("program", "").split())[:120]
        key = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40]
        if not title or not code or not key:
            flash("Please fill in at least the course title and code.", "err")
        elif key in _all_courses():
            flash(f"A course with key '{key}' already exists.", "err")
        else:
            # Create DB entry and folder
            folder = os.path.join(config.KNOWLEDGE_DIR, key)
            os.makedirs(folder, exist_ok=True)
            db.x("INSERT INTO custom_courses(key,title,code,program) VALUES(?,?,?,?)",
                 (key, title, code, program))
            flash(f"Course '{title}' ({code}) created! Now upload materials in the Knowledge Base tab.", "ok")
            return redirect(url_for("manage_courses"))
    custom = db.q("SELECT * FROM custom_courses ORDER BY id DESC")
    return render_template("t_courses.html", custom=custom, active="courses")

@app.route("/teacher/courses/<int:cid>/delete", methods=["POST"])
@admin_required
def delete_course(cid):
    r = db.q("SELECT * FROM custom_courses WHERE id=?", (cid,), one=True)
    if not r: abort(404)
    db.x("DELETE FROM custom_courses WHERE id=?", (cid,))
    # Clean up associated data
    db.x("DELETE FROM messages WHERE course=?", (r["key"],))
    db.x("DELETE FROM quiz WHERE course=?", (r["key"],))
    db.x("DELETE FROM recommendations WHERE course=?", (r["key"],))
    flash(f"Course '{r['title']}' deleted. (Files in the knowledge folder were kept.)", "ok")
    return redirect(url_for("manage_courses"))

# ------------------------------------------------------------------ teacher: manage teacher accounts (admin only)
@app.route("/teacher/teachers", methods=["GET", "POST"])
@admin_required
def manage_teachers():
    if request.method == "POST":
        f = request.form
        username = f.get("username", "").strip().lower()
        name = " ".join(f.get("name", "").split())[:60]
        pw = f.get("password", "")
        if not username or len(username) < 3:
            flash("Username must be at least 3 characters.", "err")
        elif db.q("SELECT 1 FROM teachers WHERE username=?", (username,), one=True):
            flash(f"Username '{username}' already exists.", "err")
        elif not name or len(name) < 2:
            flash("Please enter a display name.", "err")
        elif V.check_password(pw):
            flash(V.check_password(pw), "err")
        else:
            db.x("INSERT INTO teachers(username,name,pw_hash,is_admin) VALUES(?,?,?,0)",
                 (username, name, generate_password_hash(pw)))
            flash(f"Teacher account '{username}' created for {name}.", "ok")
            return redirect(url_for("manage_teachers"))
    teachers = db.q("SELECT id,username,name,is_admin,updated_at FROM teachers ORDER BY id")
    return render_template("t_teachers.html", teachers=teachers, active="teachers")

@app.route("/teacher/teachers/<int:tid>/delete", methods=["POST"])
@admin_required
def delete_teacher(tid):
    t = db.q("SELECT * FROM teachers WHERE id=?", (tid,), one=True) or abort(404)
    if t["is_admin"]:
        flash("Cannot delete the super-admin account.", "err")
    else:
        db.x("DELETE FROM teachers WHERE id=?", (tid,))
        flash(f"Teacher '{t['username']}' deleted.", "ok")
    return redirect(url_for("manage_teachers"))

# ------------------------------------------------------------------ teacher: view anonymous student feedback
@app.route("/teacher/feedback")
@teacher_required
def teacher_feedback():
    rows = db.q("""SELECT f.id, f.course, f.category, f.message, f.created_at
                   FROM feedback f ORDER BY f.id DESC LIMIT 200""")
    return render_template("t_feedback.html", rows=rows, active="feedback")

@app.route("/teacher/feedback/<int:fid>/delete", methods=["POST"])
@teacher_required
def delete_feedback(fid):
    db.x("DELETE FROM feedback WHERE id=?", (fid,))
    flash("Feedback entry removed.", "ok")
    return redirect(url_for("teacher_feedback"))

if __name__ == "__main__":
    app.run(debug=os.environ.get("DEBUG") == "1", port=int(os.environ.get("PORT", 5000)))
