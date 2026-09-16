"""
ATS-safe resume PDF renderer (Part 7).

Format constraints from the build spec, all enforced here rather than left
to a template that could drift:
  - Single column, no tables, no text boxes, no headers/footers, no images
  - Standard section headings: SUMMARY, SKILLS, EXPERIENCE, PROJECTS, EDUCATION
  - Standard font (Helvetica -- built into every PDF reader, no embedding
    needed, safer for ATS parsing than a font that might not resolve)
  - Contact info (with real hyperlinks) in the body, never in a header
  - Skills as plain comma-separated text, never a graphic or rating bar
  - PDF only -- no DOCX, per Shiva's decision
"""
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib import colors

NAME_STYLE = ParagraphStyle("Name", fontName="Helvetica-Bold", fontSize=16, spaceAfter=2)
CONTACT_STYLE = ParagraphStyle("Contact", fontName="Helvetica", fontSize=10, spaceAfter=10)
HEADING_STYLE = ParagraphStyle(
    "Heading", fontName="Helvetica-Bold", fontSize=11, spaceBefore=10, spaceAfter=4,
    textColor=colors.black, borderPadding=0,
)
BODY_STYLE = ParagraphStyle("Body", fontName="Helvetica", fontSize=10.5, leading=14, alignment=TA_LEFT)
BULLET_STYLE = ParagraphStyle(
    "Bullet", parent=BODY_STYLE, leftIndent=14, bulletIndent=2, spaceAfter=3,
)
SUBHEAD_STYLE = ParagraphStyle(
    "Subhead", fontName="Helvetica-Bold", fontSize=10.5, spaceBefore=6, spaceAfter=1,
)
DATES_STYLE = ParagraphStyle(
    "Dates", fontName="Helvetica-Oblique", fontSize=9.5, textColor=colors.HexColor("#333333"),
)


def _esc(text: str) -> str:
    """reportlab Paragraph markup treats text as a tiny HTML-like dialect --
    escape the special characters so a JD-derived string can't break layout
    or accidentally inject markup."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_resume_pdf(out_path: str, profile: dict, content: dict):
    """content is the tailored (or baseline) structured resume content:
    {summary, experience: [{org, title, dates, location, bullets}],
     projects: [{name, dates, bullets}], skills_line}."""
    doc = SimpleDocTemplate(
        out_path, pagesize=LETTER,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        title=f"{profile.get('name', 'Resume')} - Resume",
    )
    story = []

    story.append(Paragraph(_esc(profile.get("name", "")), NAME_STYLE))

    contact_bits = [_esc(profile.get("location", "")), f'<a href="mailto:{profile.get("email","")}">{_esc(profile.get("email",""))}</a>']
    if profile.get("phone"):
        contact_bits.append(_esc(profile["phone"]))
    links = profile.get("links", {})
    for label, key in (("LinkedIn", "linkedin"), ("GitHub", "github"),
                       ("Hugging Face", "huggingface"), ("Portfolio", "portfolio")):
        url = links.get(key)
        if url:
            contact_bits.append(f'<a href="{url}">{label}</a>')
    story.append(Paragraph(" &nbsp;|&nbsp; ".join(contact_bits), CONTACT_STYLE))

    if content.get("summary"):
        story.append(Paragraph("SUMMARY", HEADING_STYLE))
        story.append(Paragraph(_esc(content["summary"]), BODY_STYLE))

    if content.get("skills_line"):
        story.append(Paragraph("SKILLS", HEADING_STYLE))
        story.append(Paragraph(_esc(content["skills_line"]), BODY_STYLE))

    experience = content.get("experience", [])
    if experience:
        story.append(Paragraph("EXPERIENCE", HEADING_STYLE))
        for entry in experience:
            header = f'{_esc(entry.get("title",""))}, {_esc(entry.get("org",""))}'
            story.append(Paragraph(header, SUBHEAD_STYLE))
            meta_bits = [b for b in [entry.get("dates"), entry.get("location")] if b]
            if meta_bits:
                story.append(Paragraph(_esc(" | ".join(meta_bits)), DATES_STYLE))
            for bullet in entry.get("bullets", []):
                story.append(Paragraph(f"&bull; {_esc(bullet)}", BULLET_STYLE))

    projects = content.get("projects", [])
    if projects:
        story.append(Paragraph("PROJECTS", HEADING_STYLE))
        for proj in projects:
            header = _esc(proj.get("name", ""))
            if proj.get("link"):
                header = f'<a href="{proj["link"]}">{header}</a>'
            story.append(Paragraph(header, SUBHEAD_STYLE))
            if proj.get("dates"):
                story.append(Paragraph(_esc(proj["dates"]), DATES_STYLE))
            for bullet in proj.get("bullets", []):
                story.append(Paragraph(f"&bull; {_esc(bullet)}", BULLET_STYLE))

    education = profile.get("education", {})
    if education:
        story.append(Paragraph("EDUCATION", HEADING_STYLE))
        edu_line = f'{_esc(education.get("degree",""))}, {_esc(education.get("school",""))}'
        story.append(Paragraph(edu_line, SUBHEAD_STYLE))
        meta = f'{_esc(education.get("graduated",""))}'
        if education.get("gpa"):
            meta += f' | GPA: {education["gpa"]}'
        story.append(Paragraph(meta, DATES_STYLE))

    certs = profile.get("certifications_earned", [])
    if certs:
        story.append(Paragraph("CERTIFICATIONS", HEADING_STYLE))
        story.append(Paragraph(_esc(", ".join(certs)), BODY_STYLE))

    story.append(Spacer(1, 0))
    doc.build(story)
