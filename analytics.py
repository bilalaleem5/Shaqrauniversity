"""Aggregations for the instructor dashboard, report and recommendations."""
from collections import defaultdict
import db

MIN_ATTEMPTS = 2     # attempts needed before a topic counts as weak/strong for one student
WEAK, STRONG = 0.6, 0.8

def _acc(c, n): return round(100.0 * c / n, 1) if n else None

def compute(course):
    msgs = db.q("""SELECT m.*, s.student_id sid, s.name, s.batch, s.gender FROM messages m
                   JOIN students s ON s.id=m.student_pk WHERE m.course=? ORDER BY m.id""", (course,))
    quiz = db.q("""SELECT z.*, s.student_id sid, s.name, s.batch, s.gender FROM quiz z
                   JOIN students s ON s.id=z.student_pk WHERE z.course=? AND z.is_correct IS NOT NULL""", (course,))
    registered = db.q("SELECT COUNT(*) n FROM students", one=True)["n"]

    per = {}       # student pk -> record
    def rec(pk, r):
        return per.setdefault(pk, dict(pk=pk, student_id=r["sid"], name=r["name"], batch=r["batch"],
                                       gender=r["gender"] or "", msgs=0, quiz_n=0, quiz_ok=0,
                                       topics=defaultdict(lambda: [0, 0])))
    topic = defaultdict(lambda: dict(asked=0, n=0, ok=0))
    batch = defaultdict(lambda: dict(students=set(), msgs=0, n=0, ok=0))
    oos = []
    for m in msgs:
        r = rec(m["student_pk"], m); r["msgs"] += 1
        batch[m["batch"]]["students"].add(m["student_pk"]); batch[m["batch"]]["msgs"] += 1
        if m["in_scope"] and m["topic"]: topic[m["topic"]]["asked"] += 1
        if not m["in_scope"]: oos.append(m["question"])
    for z in quiz:
        r = rec(z["student_pk"], z); r["quiz_n"] += 1; r["quiz_ok"] += z["is_correct"]
        t = r["topics"][z["topic"] or "General"]; t[0] += 1; t[1] += z["is_correct"]
        topic[z["topic"] or "General"]["n"] += 1; topic[z["topic"] or "General"]["ok"] += z["is_correct"]
        b = batch[z["batch"]]; b["students"].add(z["student_pk"]); b["n"] += 1; b["ok"] += z["is_correct"]

    topics = sorted(({"topic": t, "asked": v["asked"], "attempts": v["n"], "accuracy": _acc(v["ok"], v["n"])}
                     for t, v in topic.items()), key=lambda x: (x["accuracy"] is None, x["accuracy"] or 0))
    weak_topics = [t for t in topics if t["accuracy"] is not None and t["attempts"] >= 3 and t["accuracy"] < WEAK * 100]
    most_asked = sorted(topics, key=lambda x: -x["asked"])[:6]

    students = []
    for r in per.values():
        weak = [t for t, (n, ok) in r["topics"].items() if n >= MIN_ATTEMPTS and ok / n < WEAK]
        strong = [t for t, (n, ok) in r["topics"].items() if n >= MIN_ATTEMPTS and ok / n >= STRONG]
        students.append(dict(pk=r["pk"], student_id=r["student_id"], name=r["name"], batch=r["batch"],
                             gender=r["gender"], msgs=r["msgs"], quiz_n=r["quiz_n"],
                             accuracy=_acc(r["quiz_ok"], r["quiz_n"]), weak=weak, strong=strong,
                             topic_stats={t: _acc(ok, n) for t, (n, ok) in r["topics"].items()}))
    students.sort(key=lambda s: (s["accuracy"] is None, s["accuracy"] or 0))

    n_ok = sum(z["is_correct"] for z in quiz)
    freq = defaultdict(int)
    for m in msgs:
        if m["in_scope"]: freq[m["question"].strip()[:160]] += 1
    top_q = sorted(freq.items(), key=lambda kv: -kv[1])[:15]
    return dict(
        course=course, registered=registered, active=len(per), messages=len(msgs), quiz_attempts=len(quiz),
        accuracy=_acc(n_ok, len(quiz)), out_of_scope=len(oos), oos_examples=oos[-8:],
        topics=topics, weak_topics=weak_topics, most_asked=most_asked, students=students,
        batches=[dict(batch=b, students=len(v["students"]), msgs=v["msgs"], accuracy=_acc(v["ok"], v["n"]))
                 for b, v in sorted(batch.items())],
        top_questions=[dict(q=q, count=c) for q, c in top_q],
        needs_help=[s for s in students if s["accuracy"] is not None and s["accuracy"] < WEAK * 100 and s["quiz_n"] >= 3][:10],
    )

def anonymised(stats):
    """Aggregates only: no names or IDs leave the server for the AI call."""
    keep = ("course", "active", "messages", "quiz_attempts", "accuracy", "out_of_scope", "oos_examples",
            "topics", "weak_topics", "most_asked", "batches", "top_questions")
    d = {k: stats[k] for k in keep}
    accs = [s["accuracy"] for s in stats["students"] if s["accuracy"] is not None]
    d["students_below_60pct"] = sum(a < 60 for a in accs)
    d["students_above_80pct"] = sum(a >= 80 for a in accs)
    return d
