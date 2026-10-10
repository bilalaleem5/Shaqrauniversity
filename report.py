import io, datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.graphics.shapes import Drawing, Rect, String
import config

NAVY = colors.HexColor("#14365d"); GREEN = colors.HexColor("#1b7f5c")
RED = colors.HexColor("#c0392b"); GREY = colors.HexColor("#eef2f6")

def _safe(s):
    """Built-in PDF fonts cannot draw Arabic: fall back to the ID for non-Latin names."""
    try: s.encode("latin-1"); return s
    except Exception: return None

def _esc(s): return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _bars(topics):
    topics = [t for t in topics if t["accuracy"] is not None][:12]
    h = 18 * len(topics) + 10
    d = Drawing(480, h)
    for i, t in enumerate(topics):
        y = h - 18 * (i + 1)
        d.add(String(0, y + 3, _safe(t["topic"][:34]) or "topic", fontSize=7))
        d.add(Rect(190, y, 260, 11, fillColor=GREY, strokeColor=None))
        c = GREEN if t["accuracy"] >= 80 else (colors.orange if t["accuracy"] >= 60 else RED)
        d.add(Rect(190, y, 2.6 * t["accuracy"], 11, fillColor=c, strokeColor=None))
        d.add(String(455, y + 3, f'{t["accuracy"]:.0f}%', fontSize=7))
    return d

def build(stats, recommendation):
    cfg = config.COURSES[stats["course"]]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=1.8*cm, bottomMargin=1.8*cm,
                            title=f"{cfg['title']} - Learning Analytics Report")
    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("h1", parent=ss["Title"], textColor=NAVY, fontSize=20, alignment=0)
    H2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=NAVY, spaceBefore=12)
    B = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13)
    S = ParagraphStyle("s", parent=B, fontSize=8, textColor=colors.grey)

    def table(rows, widths, head=True):
        t = Table(rows, colWidths=widths, repeatRows=1 if head else 0)
        st = [("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY]),
              ("GRID", (0, 0), (-1, -1), .25, colors.lightgrey)]
        if head: st += [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
        t.setStyle(TableStyle(st)); return t

    p = lambda s, st=B: Paragraph(s, st)
    el = [p("Shaqra University", S), p(f"{_esc(cfg['title'])} ({cfg['code']})", H1),
          p(f"AI Tutor Learning Analytics Report &nbsp;|&nbsp; {datetime.date.today():%d %b %Y} &nbsp;|&nbsp; "
            f"Instructor: {_esc(config.INSTRUCTOR_NAME)}", S), Spacer(1, 10)]

    acc = "n/a" if stats["accuracy"] is None else f'{stats["accuracy"]:.0f}%'
    el.append(table([["Active students", "Questions asked", "Quiz answers", "Quiz accuracy", "Outside course scope"],
                     [stats["active"], stats["messages"], stats["quiz_attempts"], acc, stats["out_of_scope"]]],
                    [3.4*cm]*5))
    el += [p("1. Performance by topic (quiz accuracy)", H2), _bars(stats["topics"])]
    if stats["weak_topics"]:
        el.append(p("<b>Weakest topics:</b> " + ", ".join(f'{_esc(t["topic"])} ({t["accuracy"]:.0f}%)' for t in stats["weak_topics"][:5])))

    el.append(p("2. What students ask about most", H2))
    el.append(table([["Topic", "Questions", "Quiz attempts", "Accuracy"]] +
                    [[_esc(t["topic"])[:60], t["asked"], t["attempts"], "-" if t["accuracy"] is None else f'{t["accuracy"]:.0f}%']
                     for t in stats["most_asked"]], [8.5*cm, 2.5*cm, 3*cm, 3*cm]))
    if stats["top_questions"]:
        el.append(p("Most frequent questions", H2))
        for q in stats["top_questions"][:8]:
            el.append(p(f'&bull; {_esc(q["q"])} <font color="grey">(x{q["count"]})</font>'))

    el.append(p("3. Batches", H2))
    el.append(table([["Batch", "Students", "Questions", "Quiz accuracy"]] +
                    [[b["batch"], b["students"], b["msgs"], "-" if b["accuracy"] is None else f'{b["accuracy"]:.0f}%']
                     for b in stats["batches"]], [4*cm, 4*cm, 4*cm, 4*cm]))

    el.append(p("4. Students (lowest accuracy first)", H2))
    rows = [["ID", "Name", "Batch", "Q", "Quiz", "Acc.", "Weak topics"]]
    for s in stats["students"][:40]:
        rows.append([s["student_id"], _safe(s["name"])[:22] if _safe(s["name"]) else "-", s["batch"], s["msgs"], s["quiz_n"],
                     "-" if s["accuracy"] is None else f'{s["accuracy"]:.0f}%',
                     Paragraph(_esc(", ".join(s["weak"][:3]) or "-")[:90], S)])
    el.append(table(rows, [2.2*cm, 3.6*cm, 1.4*cm, 1*cm, 1.2*cm, 1.4*cm, 6.2*cm]))

    el.append(p("5. Recommendations to improve the course", H2))
    for line in (recommendation or "No recommendations generated yet.").split("\n"):
        if line.strip(): el.append(p(_esc(line.strip())))
    el += [Spacer(1, 14), p("Generated automatically from AI-tutor usage and quiz data. Names written in Arabic appear as IDs in this PDF; "
                            "see the dashboard or CSV export for full names.", S)]
    doc.build(el)
    return buf.getvalue()


def question_sheet(cfg, items, kind, with_answers):
    """Printable question paper. with_answers=True adds the answer key (MCQ letters / model answers)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=1.8*cm, bottomMargin=1.8*cm,
                            title=f"{cfg['title']} - question sheet")
    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("h1", parent=ss["Title"], textColor=NAVY, fontSize=18, alignment=0)
    B = ParagraphStyle("b", parent=ss["BodyText"], fontSize=10.5, leading=15)
    Q = ParagraphStyle("q", parent=B, fontName="Helvetica-Bold", spaceBefore=10)
    A = ParagraphStyle("a", parent=B, textColor=GREEN)
    S = ParagraphStyle("s", parent=B, fontSize=8, textColor=colors.grey)
    p = lambda t, st=B: Paragraph(_esc(t), st)
    el = [p("Shaqra University", S), p(f"{cfg['title']} ({cfg['code']})", H1),
          p(("Multiple-choice" if kind == "mcq" else "Theory") + " questions" + (" - WITH ANSWERS" if with_answers else " - WITHOUT ANSWERS"), S), Spacer(1, 8)]
    for i, it in enumerate(items, 1):
        el.append(p(f"Q{i}. {it['question']}", Q))
        if kind == "mcq":
            for j, o in enumerate(it["options"]): el.append(p(f"    {'ABCD'[j]}. {o}"))
        else:
            for _ in range(3): el.append(Paragraph("&nbsp;", B)); 
            el.append(Paragraph("<font color='#aaaaaa'>" + "_" * 78 + "</font>", B))
    if with_answers:
        el += [Spacer(1, 16), Paragraph("<b>Answer key</b>", ParagraphStyle("k", parent=B, fontSize=14, textColor=NAVY))]
        for i, it in enumerate(items, 1):
            if kind == "mcq":
                el.append(p(f"Q{i}: {'ABCD'[it['correct_idx']]}. {it['options'][it['correct_idx']]}", A))
                if it.get("explanation"): el.append(p(f"    {it['explanation']}", S))
            else:
                el.append(p(f"Q{i}: {it['model_answer']}", A))
    doc.build(el)
    return buf.getvalue()
