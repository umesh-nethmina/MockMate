"""PDF version of an interview report (FR-45). Pure Python (fpdf2) with bundled DejaVu fonts, so any
Unicode in names, answers or code renders correctly and nothing depends on fonts installed on the host."""

from datetime import datetime
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

FONT_DIR = Path(__file__).resolve().parent.parent / "data" / "fonts"
DECISIONS = {"strong_hire": "Strong hire", "hire": "Hire", "no_hire": "No hire", "strong_no_hire": "Strong no hire"}
ROUNDS = {"hr": "HR", "technical": "Technical", "coding": "Coding"}
PACE = {"slow": "a bit slow", "good": "good pace", "fast": "a bit fast"}

INK = (26, 26, 26)
MUTED = (92, 92, 92)
ACCENT = (37, 87, 214)
RULE = (226, 226, 222)


class _Doc(FPDF):
    def __init__(self, title: str) -> None:
        super().__init__(format="A4")
        self.doc_title = title
        self.add_font("Sans", "", str(FONT_DIR / "DejaVuSans.ttf"))
        self.add_font("Sans", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
        self.add_font("Mono", "", str(FONT_DIR / "DejaVuSansMono.ttf"))
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(18, 16, 18)
        self.set_title(title)
        self.set_creator("MockMate")

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Sans", size=8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, f"MockMate · {self.doc_title} · page {self.page_no()}/{{nb}}", align="C")

    # ---- small helpers ----
    def h1(self, text: str) -> None:
        self.set_font("Sans", "B", 18)
        self.set_text_color(*INK)
        self.multi_cell(0, 9, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def h2(self, text: str) -> None:
        self.ln(3)
        if self.get_y() > self.h - 40:
            self.add_page()
        self.set_font("Sans", "B", 13)
        self.set_text_color(*ACCENT)
        self.multi_cell(0, 7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def h3(self, text: str) -> None:
        self.ln(1)
        self.set_font("Sans", "B", 10.5)
        self.set_text_color(*INK)
        self.multi_cell(0, 5.5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def para(self, text: str, size: float = 10, muted: bool = False) -> None:
        self.set_font("Sans", size=size)
        self.set_text_color(*(MUTED if muted else INK))
        self.multi_cell(0, size * 0.52, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def bullets(self, items: list[str]) -> None:
        self.set_font("Sans", size=10)
        self.set_text_color(*INK)
        for item in items:
            self.set_x(self.l_margin + 2)
            self.multi_cell(0, 5.2, f"•  {item}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def code(self, text: str) -> None:
        self.set_font("Mono", size=8.5)
        self.set_text_color(*INK)
        self.set_fill_color(245, 245, 242)
        self.multi_cell(0, 4.4, text.rstrip() or " ", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def render(report, generated_at: datetime | None = None) -> bytes:
    """Render a ReportOut (see app.api.sessions) to PDF bytes."""
    title = f"{report.role} ({report.level}) interview report"
    pdf = _Doc(title)
    pdf.alias_nb_pages()
    pdf.add_page()

    pdf.h1(title)
    when = report.created_at.strftime("%d %B %Y")
    pdf.para(f"{report.session_type.capitalize()} interview · {when}", size=9.5, muted=True)
    pdf.ln(3)
    pdf.set_font("Sans", "B", 26)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 12, f"{report.overall_score:.1f} / 10", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.para("Overall score: the average of correctness, clarity and depth across your answers.", 8.5, True)
    pdf.ln(2)
    pdf.para(report.summary)

    if report.questions:
        pdf.h2("Strengths")
        pdf.bullets(report.strengths or ["-"])
        pdf.h2("To improve")
        pdf.bullets(report.weaknesses or ["-"])

    if report.panel_verdict:
        v = report.panel_verdict
        pdf.h2(f"Panel decision: {'Hire' if v['decision'] == 'hire' else 'No hire'} "
               f"({v['votes_for_hire']} of {len(v['panelists'])} votes)")
        for p in v["panelists"]:
            pdf.h3(f"{p['name']}: {DECISIONS.get(p['decision'], p['decision'])}")
            pdf.para(p["reason"])
        pdf.para(v.get("summary", ""), 9, True)

    d = report.delivery
    if d and d.voice_answers:
        pdf.h2("How you spoke")
        pace = f"{d.avg_wpm:.0f} words per minute ({PACE.get(d.pace or '', '')})" if d.avg_wpm else "not measured"
        fillers = ", ".join(f'"{w}" ×{n}' for w, n in d.top_fillers.items()) or "none detected"
        pdf.bullets([
            f"Speaking pace: {pace}; aim for 110-160",
            f"Filler words: {d.total_fillers} ({fillers})",
            f"Average answer length: {d.avg_words_per_answer:.0f} words",
        ])

    for i, q in enumerate(report.questions, 1):
        label = "Code" if q.kind == "code" else ROUNDS.get(q.round, q.round)
        pdf.h2(f"Q{i} · {label} · {q.average:.1f} / 10")
        pdf.para(q.question, 10)
        names = ("Correctness", "Code quality", "Efficiency") if q.kind == "code" else (
            "Correctness", "Clarity", "Depth")
        scores = "   ".join(f"{n}: {s}" for n, s in zip(names, (q.correctness, q.clarity, q.depth), strict=True))
        pdf.para(scores, 9, True)
        if q.star:
            star = "  ".join(f"{'✓' if q.star[k] else '✗'} {k.capitalize()}"
                             for k in ("situation", "task", "action", "result"))
            pdf.para(f"STAR: {star}", 9, True)
        if q.kind == "code":
            pdf.h3(f"Your code ({'JavaScript' if q.language == 'javascript' else 'Python'}) · "
                   f"{q.tests_passed} of {q.tests_total} tests passed · {q.hints_used or 0} hint(s)")
            pdf.code(q.answer)
        else:
            pdf.h3("Your answer" + (" (spoken)" if q.is_voice else ""))
            pdf.para(q.answer)
        pdf.h3("Feedback")
        pdf.para(q.feedback)
        pdf.h3("Model answer")
        if q.kind == "code":
            pdf.code(q.model_answer)
        else:
            pdf.para(q.model_answer)

    plan = report.study_plan
    if plan:
        pdf.h2("Your study plan")
        pdf.para(plan["summary"])
        for item in plan["items"]:
            pdf.h3(f"{item['topic']} · {item['priority']} priority · about {item['hours']} h")
            pdf.para(item["why"], 9.5)
            pdf.bullets(item["actions"])
            pdf.para(f"Practise answering: \"{item['practice_question']}\"", 9.5, True)
        pdf.ln(1)
        pdf.para(f"Next mock interview: {plan['next_session']}", 9.5)

    pdf.ln(4)
    stamp = (generated_at or datetime.now()).strftime("%d %B %Y %H:%M")
    pdf.para(f"Generated by MockMate on {stamp}. Scores are AI-generated practice feedback, not a hiring decision.",
             8, True)
    return bytes(pdf.output())
