"""Fill the database with FAKE demo students/activity so the dashboard looks alive.
   python seed_demo.py          -> add ~40 demo students
   python seed_demo.py --wipe   -> remove ALL demo data (before the real students start)"""
import sys, random, json
from werkzeug.security import generate_password_hash
import db, rag, config

db.init()
if "--wipe" in sys.argv:
    ids = [r["id"] for r in db.q("SELECT id FROM students WHERE is_demo=1")]
    for i in ids:
        db.x("DELETE FROM messages WHERE student_pk=?", (i,)); db.x("DELETE FROM quiz WHERE student_pk=?", (i,))
    db.x("DELETE FROM students WHERE is_demo=1"); db.x("DELETE FROM recommendations")
    print("removed", len(ids), "demo students"); sys.exit()

random.seed(7)
first = ["Ahmed","Mohammed","Faisal","Abdullah","Khalid","Saud","Turki","Nawaf","Fahad","Sultan","Sara","Noura","Reem","Lama","Maha","Hind","Joud","Dana","Layan","Abeer"]
last = ["Alotaibi","Alharbi","Alqahtani","Alshammari","Aldosari","Alzahrani","Almutairi","Alanazi"]
Q = {"biostatistics": ["How do I calculate standard deviation in Excel?", "When should I use a t-test?", "What is the difference between parametric and non-parametric tests?",
                       "What does p-value mean?", "How do I make a histogram in Excel?", "Explain the null hypothesis", "How to calculate the median in Excel?", "What is a confidence interval?"],
     "pharmacoepi": ["What is an odds ratio?", "Difference between RCT and cohort study?", "What is pragmatic trial?", "How to search PubMed for adverse drug reactions?",
                     "What is pharmacovigilance?", "How do I build a presentation on a study?", "What is relative risk?"]}
bad = {"biostatistics": ["Lecture 6", "Chapter 12. Non-Parametric Tests"], "pharmacoepi": ["The odds ratio"]}
n = 0
for i in range(40):
    sid = f"D{2024000 + i}"
    name = f"{random.choice(first)} {random.choice(last)}"
    pk = db.x("INSERT INTO students(student_id,email,name,batch,gender,pw_hash,is_demo) VALUES(?,?,?,?,?,?,1)",
              (sid, f"demo{i}@example.org", name, random.choice(["2024", "2025", "2026"]), "male" if i < 20 else "female", generate_password_hash("Demo12345")))
    skill = random.uniform(.35, .95)
    for course in config.COURSES:
        tl = rag.topics(course)
        for _ in range(random.randint(2, 8)):
            t = random.choice(tl); q = random.choice(Q[course])
            db.x("INSERT INTO messages(student_pk,course,question,answer,topic,in_scope) VALUES(?,?,?,?,?,?)", (pk, course, q, "demo", t, 1))
        if random.random() < .08:
            db.x("INSERT INTO messages(student_pk,course,question,answer,topic,in_scope) VALUES(?,?,?,?,?,?)", (pk, course, "What is the weather today?", "out of scope", None, 0))
        for _ in range(random.randint(4, 12)):
            t = random.choice(tl); p = skill - (.3 if t in bad[course] else 0)
            ok = int(random.random() < p)
            db.x("INSERT INTO quiz(student_pk,course,topic,question,options,correct_idx,explanation,chosen_idx,is_correct) VALUES(?,?,?,?,?,?,?,?,?)",
                 (pk, course, t, "demo question", json.dumps(["A", "B", "C", "D"]), 0, "", 0 if ok else 1, ok))
    n += 1
print("seeded", n, "demo students")
