"""End-to-end test with a FAKE OpenAI client (no network). Run: python tests/test_all.py"""
import os, sys, json, re, tempfile, shutil, hashlib
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=tmp, OPENAI_API_KEY="test-key", NO_EMBED_THREAD="1", SECRET_KEY="t")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, rag, config
import app as A, db

class Msg:  # minimal OpenAI response shape
    def __init__(s, c): s.message = type("M", (), {"content": c})()
class Resp:
    def __init__(s, c): s.choices = [Msg(c)]
class Chat:
    def create(self, **kw):
        m = kw["messages"]; user = m[-1]["content"]; sysm = m[0]["content"] if m[0]["role"] == "system" else ""
        if "Grade the STUDENT ANSWER" in user:
            return Resp(json.dumps({"score": 85 if "mean" in user.split("STUDENT ANSWER:")[1].lower() else 20, "feedback": "Good effort."}))
        if "multiple-choice question" in user and "ONE" in user:
            return Resp(json.dumps({"question": "Which is the mean?", "options": ["A1", "B1", "C1", "D1"], "correct_idx": 2, "explanation": "Because."}))
        if "short-answer (theory) question" in user and "ONE" in user:
            return Resp(json.dumps({"question": "Explain the mean.", "model_answer": "The mean is the average of all values."}))
        if "exam questions" in user:
            n = int(re.search(r"exactly (\d+)", user).group(1)); mcq = "multiple-choice" in user
            qs = [({"topic": "Lecture 3", "question": f"Q{i}?", "options": ["a", "b", "c", "d"], "correct_idx": i % 4, "explanation": "e"} if mcq else
                   {"topic": "Lecture 3", "question": f"Q{i}?", "model_answer": f"Answer {i}."}) for i in range(n)]
            return Resp(json.dumps({"questions": qs}))
        if "anonymised analytics" in user: return Resp("1. Re-teach the weak topics.\n2. Add practice sets.")
        if "COURSE MATERIAL" in sysm:
            return Resp(rag.OOS + " That is outside this course." if "weather" in user else "The standard deviation is computed with =STDEV.S in Excel.")
        raise AssertionError("unexpected prompt: " + user[:80])
class Emb:
    def create(self, model, input):
        out = []
        for t in input:
            v = np.zeros(64)
            for w in re.findall(r"\w+", t.lower()): v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1
            out.append(type("E", (), {"embedding": v.tolist()})())
        return type("R", (), {"data": out})()
class Fake: chat = type("C", (), {"completions": Chat()})(); embeddings = Emb()
rag._client = Fake()

fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(info)))
    if not cond: fails.append(name)

def tok(c):
    with c.session_transaction() as s:
        if "csrf" in s: return s["csrf"]
    c.get("/login")
    with c.session_transaction() as s: return s["csrf"]
def post(c, url, data=None, **kw): d = dict(data or {}); d["csrf"] = tok(c); return c.post(url, data=d, **kw)
def jpost(c, url, js): return c.post(url, json=js, headers={"X-CSRF": tok(c)})

# ---- index + embeddings
for course in config.COURSES: rag.build_chunks(course); rag.build_embeddings(course)
check("embeddings built", all(os.path.exists(rag.paths(c)[1]) for c in config.COURSES))
r = rag.retrieve("pharmacoepi", "what is an odds ratio", 3)
check("retrieval returns chunks", len(r) == 3 and "score" in r[0])

# ---- teacher auth
t = A.app.test_client()
check("teacher pages redirect when logged out", t.get("/teacher").status_code == 302 and t.get("/teacher/students").status_code == 302)
check("csrf required on POST", t.post("/teacher/login", data={"username": "teacher", "password": "x"}).status_code == 400)
check("wrong teacher password", b"Wrong username" in post(t, "/teacher/login", {"username": "teacher", "password": "nope"}).data)
r = post(t, "/teacher/login", {"username": "teacher", "password": config.TEACHER_PASSWORD}); check("teacher default login", r.status_code == 302)
for u in ("/teacher", "/teacher?course=pharmacoepi", "/teacher/students", "/teacher/blocked", "/teacher/settings", "/teacher/question-bank"):
    check("teacher page " + u, t.get(u).status_code == 200)

# lockout
x = A.app.test_client()
for _ in range(5): post(x, "/teacher/login", {"username": "teacher", "password": "bad"})
check("lockout after 5 failures", b"Too many" in post(x, "/teacher/login", {"username": "teacher", "password": config.TEACHER_PASSWORD}).data)
db.x("DELETE FROM throttle")

# ---- student signup checks
s = A.app.test_client()
good = dict(name="Ali Hassan", student_id="S100", email="ali@example.com", batch="2025", gender="male", password="Pass12345", password2="Pass12345")
def reg(**ch): d = dict(good); d.update(ch); return post(s, "/register", d)
for label, ch, msg in [("bad email", dict(email="nope"), b"valid email"), ("disposable email", dict(email="a@mailinator.com"), b"Temporary"),
                       ("short password", dict(password="a1", password2="a1"), b"at least 8"), ("no digit", dict(password="abcdefghij", password2="abcdefghij"), b"letters and numbers"),
                       ("mismatch", dict(password2="Other12345"), b"do not match"), ("bad batch", dict(batch="1999"), b"batch"), ("short name", dict(name="Al"), b"full name"),
                       ("bad id", dict(student_id="a b"), b"Student ID")]:
    check("signup rejects " + label, msg in reg(**ch).data)
check("signup ok", reg().status_code == 302)
s2 = A.app.test_client()
check("duplicate id rejected", b"already registered" in post(s2, "/register", dict(good, email="other@example.com")).data)
check("duplicate email rejected", b"already registered" in post(s2, "/register", dict(good, student_id="S101")).data)

# ---- student login
s.get("/logout"); 
check("login by student id", post(s, "/login", {"identifier": "S100", "password": "Pass12345"}).status_code == 302)
s.get("/logout")
check("login by email", post(s, "/login", {"identifier": "ALI@example.com", "password": "Pass12345"}).status_code == 302)
check("student cannot open teacher area", s.get("/teacher").status_code == 302)
check("courses page", s.get("/courses").status_code == 200 and s.get("/chat/biostatistics").status_code == 200 and s.get("/chat/nope").status_code == 404)

# ---- chat
r = jpost(s, "/api/chat/biostatistics", {"message": "how to calculate standard deviation in excel", "history": []}).get_json()
check("chat answer in scope", r["in_scope"] == 1 and "STDEV" in r["answer"] and r["sources"], r)
r = jpost(s, "/api/chat/biostatistics", {"message": "what is the weather today"}).get_json(); check("chat out of scope", r["in_scope"] == 0)
check("intro", jpost(s, "/api/chat/pharmacoepi", {"intro": True}).get_json()["in_scope"] == 1)
check("empty message rejected", jpost(s, "/api/chat/biostatistics", {"message": "  "}).status_code == 400)
check("chat without csrf rejected", s.post("/api/chat/biostatistics", json={"message": "hi"}).status_code == 400)

# ---- quiz: mcq / theory graded / study / reveal
q = jpost(s, "/api/quiz/biostatistics/next", {"kind": "mcq", "topic": "Lecture 5"}).get_json()
check("mcq has no answer leaked", "correct_idx" not in q and len(q["options"]) == 4, q)
a = jpost(s, "/api/quiz/answer", {"id": q["id"], "chosen": 2}).get_json(); check("mcq correct", a["correct"] and a["total"] == 1)
check("mcq double answer blocked", jpost(s, "/api/quiz/answer", {"id": q["id"], "chosen": 1}).status_code == 400)
q = jpost(s, "/api/quiz/biostatistics/next", {"kind": "mcq"}).get_json()
a = jpost(s, "/api/quiz/answer", {"id": q["id"], "chosen": 0}).get_json(); check("mcq wrong", not a["correct"] and a["total"] == 2 and a["right"] == 1)
check("mcq invalid choice", jpost(s, "/api/quiz/answer", {"id": jpost(s, "/api/quiz/biostatistics/next", {"kind": "mcq"}).get_json()["id"], "chosen": 9}).status_code == 400)
q = jpost(s, "/api/quiz/biostatistics/next", {"kind": "theory", "topic": "Lecture 3"}).get_json()
check("theory has no model answer yet", "model_answer" not in q)
check("theory short answer rejected", jpost(s, "/api/quiz/theory", {"id": q["id"], "answer": "x"}).status_code == 400)
r = jpost(s, "/api/quiz/theory", {"id": q["id"], "answer": "The mean is the sum divided by n."}).get_json()
check("theory graded + model answer shown", r["score"] == 85 and r["correct"] and "average" in r["model_answer"], r)
check("theory double answer blocked", jpost(s, "/api/quiz/theory", {"id": q["id"], "answer": "again again"}).status_code == 400)
q = jpost(s, "/api/quiz/biostatistics/next", {"kind": "theory"}).get_json()
r = jpost(s, "/api/quiz/theory", {"id": q["id"], "reveal": True}).get_json(); check("theory reveal without answering", r.get("revealed") and "average" in r["model_answer"])
q = jpost(s, "/api/quiz/biostatistics/next", {"kind": "study"}).get_json(); check("study mode shows answer immediately", "average" in q["model_answer"])
other = A.app.test_client(); post(other, "/register", dict(good, student_id="S200", email="b@example.com", name="Bob Marley"))
check("cannot answer someone else's question", jpost(other, "/api/quiz/answer", {"id": 1, "chosen": 0}).status_code == 404)

# ---- teacher sees the student + data
r = t.get("/teacher/students").data
check("teacher sees both students", b"Ali Hassan" in r and b"ali@example.com" in r and b"Bob Marley" in r)
pk = db.q("SELECT id FROM students WHERE student_id='S100'", one=True)["id"]
d = t.get(f"/teacher/student/{pk}?course=biostatistics").data
check("student detail shows questions, logins, theory", b"standard deviation" in d and b"Recent logins" in d and b"The mean is the sum" in d)
check("dashboard has data", b"Quiz accuracy by topic" in t.get("/teacher?course=biostatistics").data)
r = post(t, "/teacher/recommend?course=biostatistics"); check("recommendations", r.status_code == 302 and b"Re-teach" in t.get("/teacher?course=biostatistics").data)
r = t.get("/teacher/report.pdf?course=biostatistics"); check("pdf report", r.mimetype == "application/pdf" and r.data[:4] == b"%PDF")
r = t.get("/teacher/export.csv"); check("csv export", b"ali@example.com" in r.data)
for kind in ("mcq", "theory"):
    for wa in ("0", "1"):
        r = post(t, "/teacher/question-bank", {"course": "biostatistics", "kind": kind, "count": "5", "with_answers": wa})
        check(f"question sheet {kind} with_answers={wa}", r.mimetype == "application/pdf" and r.data[:4] == b"%PDF", r.status_code)

# ---- user management
S = lambda pkx, act: post(t, f"/teacher/student/{pkx}/action", {"action": act})
S(pk, "suspend"); s.get("/courses")
check("suspended student is kicked out", s.get("/courses").status_code == 302)
s.get("/logout"); check("suspended student cannot log in", b"suspended" in post(s, "/login", {"identifier": "S100", "password": "Pass12345"}).data)
S(pk, "activate"); check("activated student can log in", post(s, "/login", {"identifier": "S100", "password": "Pass12345"}).status_code == 302)
S(pk, "block_email"); s.get("/courses")
check("blocked email is kicked out", s.get("/courses").status_code == 302)
s.get("/logout"); check("blocked email cannot log in", b"not allowed" in post(s, "/login", {"identifier": "S100", "password": "Pass12345"}).data)
check("blocked email cannot sign up again", b"not allowed" in post(A.app.test_client(), "/register", dict(good, student_id="S999")).data)
bid = db.q("SELECT id FROM blocked WHERE pattern='ali@example.com'", one=True)["id"]
post(t, f"/teacher/blocked/{bid}/remove"); check("unblock works", post(s, "/login", {"identifier": "S100", "password": "Pass12345"}).status_code == 302)
post(t, "/teacher/blocked", {"pattern": "badschool.edu", "reason": "test"})
check("domain block", b"not allowed" in post(A.app.test_client(), "/register", dict(good, student_id="S555", email="z@badschool.edu")).data)
check("invalid block pattern rejected", b"valid email" in t.get(post(t, "/teacher/blocked", {"pattern": "###"}).headers["Location"]).data)
r = S(pk, "reset_password"); msg = t.get(r.headers["Location"]).data.decode()
m = re.search(r"\(S100\): (\w{10})", msg); check("reset password shows temp password", bool(m))
s.get("/logout"); check("old password stops working", b"Wrong" in post(s, "/login", {"identifier": "S100", "password": "Pass12345"}).data)
check("temp password works", post(s, "/login", {"identifier": "S100", "password": m.group(1)}).status_code == 302)
pk2 = db.q("SELECT id FROM students WHERE student_id='S200'", one=True)["id"]
jpost(other, "/api/chat/biostatistics", {"message": "what is standard deviation"})
S(pk2, "delete_block")
check("delete removes user and data", not db.q("SELECT 1 FROM students WHERE id=?", (pk2,)) and not db.q("SELECT 1 FROM messages WHERE student_pk=?", (pk2,)))
check("delete+block blocks the email", bool(db.q("SELECT 1 FROM blocked WHERE pattern='b@example.com'")))
S(pk, "delete"); check("plain delete", not db.q("SELECT 1 FROM students WHERE id=?", (pk,)))

# ---- teacher password change
def setpw(cur, new, conf): return t.get(post(t, "/teacher/settings", {"kind": "password", "current": cur, "new": new, "confirm": conf}).headers["Location"]).data
check("wrong current password", b"Current password is wrong" in setpw("bad", "NewPass123", "NewPass123"))
check("weak new password", b"at least 8" in setpw(config.TEACHER_PASSWORD, "abc", "abc"))
check("mismatch", b"do not match" in setpw(config.TEACHER_PASSWORD, "NewPass123", "NewPass124"))
check("password changed", b"changed successfully" in setpw(config.TEACHER_PASSWORD, "NewPass123", "NewPass123"))
t2 = A.app.test_client()
check("old teacher password rejected", b"Wrong" in post(t2, "/teacher/login", {"username": "teacher", "password": config.TEACHER_PASSWORD}).data)
check("new teacher password works", post(t2, "/teacher/login", {"username": "teacher", "password": "NewPass123"}).status_code == 302)

shutil.rmtree(tmp, ignore_errors=True)
print("\n" + ("ALL TESTS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
