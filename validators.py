import re
import config

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
DOMAIN_RE = re.compile(r"^[a-z0-9\-]+(\.[a-z0-9\-]+)*\.[a-z]{2,}$")
SID_RE = re.compile(r"^[A-Za-z0-9\-_]{3,20}$")
DISPOSABLE = {"mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com", "yopmail.com",
              "trashmail.com", "sharklasers.com", "getnada.com", "throwawaymail.com", "maildrop.cc"}

def norm_email(e): return (e or "").strip().lower()

def check_password(pw):
    if len(pw) < 8: return "Password must be at least 8 characters."
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw): return "Password must contain letters and numbers."
    if len(pw) > 100: return "Password is too long."
    return None

def check_registration(name, student_id, email, batch, pw, batches):
    """Returns an error string or None."""
    if len(name.strip()) < 3 or len(name) > 80: return "Please enter your full name (3-80 characters)."
    if not SID_RE.match(student_id): return "Student ID must be 3-20 letters/numbers."
    if not EMAIL_RE.match(email): return "Please enter a valid email address."
    dom = email.split("@")[1]
    if dom in DISPOSABLE: return "Temporary email addresses are not allowed."
    if config.ALLOWED_EMAIL_DOMAINS and dom not in config.ALLOWED_EMAIL_DOMAINS:
        return "Please use your university email (" + ", ".join("@" + d for d in config.ALLOWED_EMAIL_DOMAINS) + ")."
    if batch not in batches: return "Please choose your batch."
    return check_password(pw)

def block_pattern(p):
    """'a@b.com' stays an email; 'b.com' or '@b.com' becomes the domain rule '@b.com'."""
    p = (p or "").strip().lower()
    if not p: return None
    if "@" not in p or p.startswith("@"):
        d = p.lstrip("@")
        return "@" + d if DOMAIN_RE.match(d) else None
    return p if EMAIL_RE.match(p) else None

def is_blocked(email, patterns):
    email = norm_email(email)
    if not email: return False
    dom = "@" + email.split("@")[-1]
    return any(p == email or p == dom for p in patterns)
