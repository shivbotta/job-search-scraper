"""
ATS-safe resume PDF renderer (Part 7) -- Harvard Business School format.

HBS-style conventions applied here:
  - Name centered at top; contact line centered below it, hyperlinked
  - Education listed before Experience (standard for students/new grads)
  - Each entry uses a two-column header line: bold org/school name with
    location right-aligned on the same line, then an italic title/degree
    line with dates right-aligned on the same line
  - Single column overall, no images/headers-footers -- the two-column
    alignment is per-line only (a real, common ATS-safe pattern; the text
    itself still reads top-to-bottom in normal order for a parser)
  - Tightened margins/spacing/bullet counts to fit one page

Hyperlinks: LinkedIn, portfolio site, GitHub, and Hugging Face in the
contact line; HypeSquad links to hypesquad.app (its real URL, per
profile.json); KwikJobs links to KWIKJOBS_URL below -- a placeholder until
Shiva provides the real one, since profile.json doesn't have it and this
tool never fabricates a link.
"""
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors

KWIKJOBS_URL = "https://kwikjobs.co/"
HYPESQUAD_URL = "https://hypesquad.app"

PAGE_MARGIN = 0.5 * inch
COL_SPLIT = (5.3 * inch, 1.7 * inch)

NAME_STYLE = ParagraphStyle("Name", fontName="Helvetica-Bold", fontSize=16,
                             alignment=TA_CENTER, spaceAfter=2)
CONTACT_STYLE = ParagraphStyle("Contact", fontName="Helvetica", fontSize=9.5,
                                alignment=TA_CENTER, spaceAfter=8)
HEADING_STYLE = ParagraphStyle(
    "Heading", fontName="Helvetica-Bold", fontSize=10.5, spaceBefore=7, spaceAfter=3,
    textColor=colors.black, borderWidth=0.5, borderColor=colors.black,
    borderPadding=(0, 0, 2, 0),
)
BODY_STYLE = ParagraphStyle("Body", fontName="Helvetica", fontSize=9.5, leading=12.5, alignment=TA_LEFT)
BULLET_STYLE = ParagraphStyle(
    "Bullet", parent=BODY_STYLE, leftIndent=12, bulletIndent=0, spaceAfter=2, fontSize=9.3, leading=12,
)
ORG_STYLE = ParagraphStyle("Org", fontName="Helvetica-Bold", fontSize=10, spaceBefore=5)
TITLE_STYLE = ParagraphStyle("TitleLine", fontName="Helvetica-Oblique", fontSize=9.5, spaceAfter=2)
RIGHT_STYLE = ParagraphStyle("Right", fontName="Helvetica", fontSize=9.5, alignment=TA_RIGHT)
RIGHT_ITALIC_STYLE = ParagraphStyle("RightItalic", fontName="Helvetica-Oblique", fontSize=9.5, alignment=TA_RIGHT)

MAX_BULLETS_PER_EXPERIENCE = 4
MAX_PROJECTS = 2
MAX_BULLETS_PER_PROJECT = 2


def _esc(text: str) -> str:
    """reportlab Paragraph markup treats text as a tiny HTML-like dialect --
    escape special characters so JD-derived text can't break layout or
    inject markup."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _two_col(left_html: str, right_text: str, left_style, right_style) -> Table:
    row = [[Paragraph(left_html, left_style), Paragraph(_esc(right_text or ""), right_style)]]
    t = Table(row, colWidths=list(COL_SPLIT))
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _link(text: str, url: str) -> str:
    return f'<a href="{url}"><u>{_esc(text)}</u></a>' if url else _esc(text)


ENTRY_LINKS = {"KwikJobs": KWIKJOBS_URL, "HypeSquad": HYPESQUAD_URL}


def render_resume_pdf(out_path: str, profile: dict, content: dict):
    """content: {summary, experience: [{org, title, dates, location, bullets}],
    projects: [{name, dates, link, bullets}], skills_line}."""
    doc = SimpleDocTemplate(
        out_path, pagesize=LETTER,
        topMargin=PAGE_MARGIN, bottomMargin=PAGE_MARGIN,
        leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
        title=f"{profile.get('name', 'Resume')} - Resume",
    )
    story = []

    story.append(Paragraph(_esc(profile.get("name", "")), NAME_STYLE))

    contact_bits = [_esc(profile.get("location", ""))]
    if profile.get("phone"):
        contact_bits.append(_esc(profile["phone"]))
    contact_bits.append(f'<a href="mailto:{profile.get("email","")}">{_esc(profile.get("email",""))}</a>')
    links = profile.get("links", {})
    for label, key in (("LinkedIn", "linkedin"), ("GitHub", "github"),
                       ("Hugging Face", "huggingface"), ("Website", "portfolio")):
        url = links.get(key)
        if url:
            contact_bits.append(f'<a href="{url}">{label}</a>')
    story.append(Paragraph(" &nbsp;|&nbsp; ".join(contact_bits), CONTACT_STYLE))

    # EDUCATION -- before Experience, HBS convention for students/new grads
    education = profile.get("education", {})
    if education:
        story.append(Paragraph("EDUCATION", HEADING_STYLE))
        story.append(_two_col(f'<b>{_esc(education.get("school",""))}</b>', "", ORG_STYLE, RIGHT_STYLE))
        gpa = f' &nbsp;|&nbsp; GPA: {education["gpa"]}' if education.get("gpa") else ""
        story.append(_two_col(f'{_esc(education.get("degree",""))}{gpa}',
                               education.get("graduated", ""), TITLE_STYLE, RIGHT_ITALIC_STYLE))

    if content.get("summary"):
        story.append(Paragraph("SUMMARY", HEADING_STYLE))
        story.append(Paragraph(_esc(content["summary"]), BODY_STYLE))

    experience = content.get("experience", [])
    if experience:
        story.append(Paragraph("EXPERIENCE", HEADING_STYLE))
        for entry in experience:
            org = entry.get("org", "")
            org_html = f'<b>{_link(org, ENTRY_LINKS.get(org))}</b>'
            story.append(_two_col(org_html, entry.get("location", ""), ORG_STYLE, RIGHT_STYLE))
            story.append(_two_col(_esc(entry.get("title", "")), entry.get("dates", ""),
                                   TITLE_STYLE, RIGHT_ITALIC_STYLE))
            for bullet in entry.get("bullets", [])[:MAX_BULLETS_PER_EXPERIENCE]:
                story.append(Paragraph(f"&bull;&nbsp; {_esc(bullet)}", BULLET_STYLE))

    projects = content.get("projects", [])
    if projects:
        story.append(Paragraph("PROJECTS", HEADING_STYLE))
        for proj in projects[:MAX_PROJECTS]:
            name_html = f'<b>{_link(proj.get("name",""), proj.get("link"))}</b>'
            story.append(_two_col(name_html, proj.get("dates", ""), ORG_STYLE, RIGHT_ITALIC_STYLE))
            for bullet in proj.get("bullets", [])[:MAX_BULLETS_PER_PROJECT]:
                story.append(Paragraph(f"&bull;&nbsp; {_esc(bullet)}", BULLET_STYLE))

    if content.get("skills_line"):
        story.append(Paragraph("SKILLS", HEADING_STYLE))
        story.append(Paragraph(_esc(content["skills_line"]), BODY_STYLE))

    certs = profile.get("certifications_earned", [])
    if certs:
        story.append(Paragraph("CERTIFICATIONS", HEADING_STYLE))
        story.append(Paragraph(_esc(", ".join(certs[:6])), BODY_STYLE))

    story.append(Spacer(1, 0))
    doc.build(story)
