import os
from dotenv import load_dotenv
load_dotenv()

BASE = os.path.dirname(os.path.abspath(__file__))
IS_VERCEL = bool(os.environ.get("VERCEL"))
REPO_DATA_DIR = os.path.join(BASE, "data")

if IS_VERCEL:
    DATA_DIR = os.environ.get("DATA_DIR", "/tmp/data")
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(REPO_DATA_DIR):
        import shutil
        for item in os.listdir(REPO_DATA_DIR):
            if item.endswith((".db-wal", ".db-shm", ".db-journal")):
                continue
            s = os.path.join(REPO_DATA_DIR, item)
            d = os.path.join(DATA_DIR, item)
            if not os.path.exists(d) and os.path.isfile(s):
                try: shutil.copy2(s, d)
                except Exception: pass
    KNOWLEDGE_DIR = os.environ.get("KNOWLEDGE_DIR", "/tmp/knowledge")
    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
    if os.path.exists(os.path.join(BASE, "knowledge")):
        import shutil
        for cname in os.listdir(os.path.join(BASE, "knowledge")):
            sdir = os.path.join(BASE, "knowledge", cname)
            ddir = os.path.join(KNOWLEDGE_DIR, cname)
            if not os.path.exists(ddir) and os.path.isdir(sdir):
                try: shutil.copytree(sdir, ddir)
                except Exception: pass
else:
    DATA_DIR = os.environ.get("DATA_DIR", REPO_DATA_DIR)
    os.makedirs(DATA_DIR, exist_ok=True)
    KNOWLEDGE_DIR = os.path.join(BASE, "knowledge")
    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)

SECRET_KEY = os.environ.get("SECRET_KEY", "shaqra-academic-tutor-secret-key-2026-v2")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")
MOCK_LLM = os.environ.get("MOCK_LLM", "0") == "1"   # offline testing, no API calls
INSTRUCTOR_NAME = os.environ.get("INSTRUCTOR_NAME", "Course Instructor")
# Teacher account created automatically on first start (change the password inside the portal afterwards)
TEACHER_USERNAME = os.environ.get("TEACHER_USERNAME", "teacher")
TEACHER_PASSWORD = os.environ.get("TEACHER_PASSWORD", "Shaqra@Teacher2026")
# Optional: only allow these email domains for student signup, e.g. "su.edu.sa,gmail.com" (empty = any domain)
ALLOWED_EMAIL_DOMAINS = [d.strip().lower() for d in os.environ.get("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()]

COURSES = {
    "biostatistics": {
        "title": "Biostatistics",
        "code": "MEDI 1201",
        "program": "PharmD, College of Pharmacy",
        "folder": os.path.join(KNOWLEDGE_DIR, "biostatistics"),
        "intro_query": "course description objectives learning outcomes course content topics",
        "style": (
            "You are the AI teaching assistant for the Biostatistics course (MEDI 1201, PharmD, Shaqra University). "
            "Teach at student level, keep it simple. Whenever a question involves calculating or analysing data, "
            "show how to do it step by step in Microsoft Excel (name the exact functions or Data Analysis ToolPak "
            "steps) using small made-up examples consistent with the course material. Encourage the student to "
            "reason and verify results themselves rather than just copying answers."
        ),
        "builtin": True,
    },
    "pharmacoepi": {
        "title": "Research Methods & Pharmacoepidemiology",
        "code": "PHP 417",
        "program": "PharmD, College of Pharmacy",
        "folder": os.path.join(KNOWLEDGE_DIR, "pharmacoepi"),
        "intro_query": "course description objectives learning outcomes course content topics",
        "style": (
            "You are the AI teaching assistant for Research Methods and Pharmacoepidemiology (PHP 417, PharmD, "
            "Shaqra University). Teach at student level. When relevant, help students learn how to search for "
            "scientific articles (for example building a PubMed search with keywords and Boolean operators, "
            "reading an abstract, judging a study design) and how to structure a short scientific presentation "
            "on a topic from the course. Stay within the course topics."
        ),
        "builtin": True,
    },
}

def get_all_courses():
    """Return COURSES dict merged with any dynamic courses from the DB."""
    import db
    all_c = dict(COURSES)
    for r in db.q("SELECT * FROM custom_courses"):
        key = r["key"]
        folder = os.path.join(KNOWLEDGE_DIR, key)
        os.makedirs(folder, exist_ok=True)
        all_c[key] = {
            "title": r["title"],
            "code": r["code"],
            "program": r["program"] or "",
            "folder": folder,
            "intro_query": r["intro_query"] or "course description objectives learning outcomes",
            "style": r["style"] or (
                f"You are the AI teaching assistant for {r['title']} ({r['code']}, Shaqra University). "
                "Teach at student level. Answer only from the course material provided."
            ),
            "builtin": False,
            "db_id": r["id"],
        }
    return all_c
