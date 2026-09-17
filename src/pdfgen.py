"""
Resume PDF renderer (Part 7) -- Harvard Business School layout, typeset
rather than templated.

Still single column, no color, no icons, no graphics, ATS-safe. Everything
below is spacing, alignment and type hierarchy only:

  - One typeface family with real weights (Charter: Roman/Italic/Bold),
    embedded. Falls back to Times if the system font isn't present.
  - Deliberate vertical rhythm: bullets sit tight within an entry, entries
    breathe a little, sections breathe more. Uniform spacing everywhere is
    exactly what makes a resume look machine-made, so it is avoided.
  - Section headings are letter-spaced small caps with a hairline rule,
    not just bolded body text.
  - Dates/locations are right-aligned against their org/role line via a
    borderless two-column row, so they sit on a true right margin.
  - Fit pass: the page is rendered at several spacing scales and the most
    generous one that still fits on a single page wins. That avoids both
    cramped type and a big empty gap at the bottom.
  - Widow control: the last two words of every paragraph are joined with a
    non-breaking space so no line ends on a single orphaned word.

Hyperlinks: contact-line items are underlined (they're navigational);
company and project names are linked but not underlined, which keeps the
body clean. KwikJobs/HypeSquad URLs are real, from Shiva directly and from
profile.json respectively -- never fabricated.
"""
import io
import os

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, Flowable, KeepTogether)
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

KWIKJOBS_URL = "https://kwikjobs.co/"
HYPESQUAD_URL = "https://hypesquad.app"
ENTRY_LINKS = {"KwikJobs": KWIKJOBS_URL, "HypeSquad": HYPESQUAD_URL}

PAGE_W, PAGE_H = LETTER
MARGIN_X = 0.66 * inch
MARGIN_TOP = 0.52 * inch
MARGIN_BOTTOM = 0.5 * inch
CONTENT_W = PAGE_W - 2 * MARGIN_X

INK = colors.HexColor("#111111")
MUTED = colors.HexColor("#444444")
RULE = colors.HexColor("#B8B5B0")

MAX_BULLETS_PER_EXPERIENCE = 4
MAX_PROJECTS = 2
MAX_BULLETS_PER_PROJECT = 2

_CHARTER = "/System/Library/Fonts/Supplemental/Charter.ttc"


def _register_fonts() -> tuple[str, str, str]:
    """Returns (regular, bold, italic) font names. Charter is a refined
    print serif that holds up at 9-10pt; Times is the fallback so this
    still renders on a machine without the macOS font."""
    try:
        if os.path.exists(_CHARTER):
            pdfmetrics.registerFont(TTFont("Charter", _CHARTER, subfontIndex=0))
            pdfmetrics.registerFont(TTFont("Charter-Italic", _CHARTER, subfontIndex=1))
            pdfmetrics.registerFont(TTFont("Charter-Bold", _CHARTER, subfontIndex=3))
            pdfmetrics.registerFontFamily(
                "Charter", normal="Charter", bold="Charter-Bold", italic="Charter-Italic"
            )
            return "Charter", "Charter-Bold", "Charter-Italic"
    except Exception:
        pass
    return "Times-Roman", "Times-Bold", "Times-Italic"


FONT, FONT_BOLD, FONT_ITALIC = _register_fonts()


def _esc(text: str) -> str:
    """Paragraph markup is a small HTML-like dialect -- escape so JD-derived
    text can't break layout or inject markup."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _no_widow(text: str) -> str:
    """Bind the final two words so a wrapped line never ends on a single
    orphaned word."""
    parts = text.rsplit(" ", 1)
    return f"{parts[0]}&nbsp;{parts[1]}" if len(parts) == 2 else text


def _clean_bullet(text: str) -> str:
    """Consistent bullet punctuation: no terminal period, no stray
    whitespace. Mixed punctuation across bullets is a tell."""
    return (text or "").strip().rstrip(".").strip()


def _link(text: str, url: str, underline: bool = False) -> str:
    inner = _esc(text)
    if not url:
        return inner
    body = f"<u>{inner}</u>" if underline else inner
    return f'<a href="{url}">{body}</a>'


class SectionHeading(Flowable):
    """Letter-spaced caps heading with a hairline rule beneath it.

    Drawn on the canvas rather than as a Paragraph because reportlab has no
    letter-spacing in paragraph styles, and faking it by putting spaces
    between characters would mangle the text layer that an ATS reads.
    setCharSpace keeps the string intact ("EXPERIENCE" extracts as one
    word) while still spacing the glyphs.
    """

    def __init__(self, text, size, tracking, gap_to_rule, space_before, space_after):
        super().__init__()
        self.text = text.upper()
        self.size = size
        self.tracking = tracking
        self.gap_to_rule = gap_to_rule
        self.spaceBefore = space_before
        self.spaceAfter = space_after
        self.width = CONTENT_W

    def wrap(self, avail_w, avail_h):
        self.width = avail_w
        return avail_w, self.size + self.gap_to_rule + 1.2

    def draw(self):
        c = self.canv
        rule_y = 0.8
        baseline = rule_y + self.gap_to_rule
        # Character spacing is a text-object property (Tc), not a canvas one.
        to = c.beginText(0, baseline)
        to.setFont(FONT_BOLD, self.size)
        to.setCharSpace(self.tracking)
        to.setFillColor(INK)
        to.textOut(self.text)
        c.drawText(to)
        c.setStrokeColor(RULE)
        c.setLineWidth(0.5)
        c.line(0, rule_y, self.width, rule_y)


class HeaderRule(Flowable):
    """Hairline under the name/contact block."""

    def __init__(self, space_before, space_after):
        super().__init__()
        self.spaceBefore = space_before
        self.spaceAfter = space_after
        self.width = CONTENT_W

    def wrap(self, avail_w, avail_h):
        self.width = avail_w
        return avail_w, 0.6

    def draw(self):
        self.canv.setStrokeColor(RULE)
        self.canv.setLineWidth(0.6)
        self.canv.line(0, 0, self.width, 0)


def _styles(s: float, f: float = 1.0) -> dict:
    """`s` scales spacing, `f` scales type size -- both are tuned by the fit
    pass. Type only moves within a narrow band (roughly 9pt-10pt body); the
    point is filling the page honestly, not inflating text to hide thin
    content."""
    return {
        "name": ParagraphStyle(
            "Name", fontName=FONT_BOLD, fontSize=18 * f, leading=21 * f, alignment=TA_CENTER,
            textColor=INK, spaceAfter=3.5 * s,
        ),
        "contact": ParagraphStyle(
            "Contact", fontName=FONT, fontSize=8.7 * f, leading=11.5 * f, alignment=TA_CENTER,
            textColor=MUTED,
        ),
        "body": ParagraphStyle(
            "Body", fontName=FONT, fontSize=9.5 * f, leading=12.4 * f, alignment=TA_LEFT,
            textColor=INK,
        ),
        "org": ParagraphStyle(
            "Org", fontName=FONT_BOLD, fontSize=10.2 * f, leading=12.6 * f, textColor=INK,
        ),
        "role": ParagraphStyle(
            "Role", fontName=FONT_ITALIC, fontSize=9.5 * f, leading=12 * f, textColor=INK,
        ),
        "right": ParagraphStyle(
            "Right", fontName=FONT, fontSize=9 * f, leading=12.6 * f, alignment=TA_RIGHT,
            textColor=MUTED,
        ),
        "right_italic": ParagraphStyle(
            "RightItalic", fontName=FONT_ITALIC, fontSize=9 * f, leading=12 * f,
            alignment=TA_RIGHT, textColor=MUTED,
        ),
        "bullet": ParagraphStyle(
            "Bullet", fontName=FONT, fontSize=9.4 * f, leading=12.1 * f, textColor=INK,
            leftIndent=11.5, bulletIndent=1.5, spaceAfter=1.7 * s,
        ),
    }


def _two_col(left_html, right_html, left_style, right_style, space_before=0.0):
    left = Paragraph(left_html, left_style)
    right = Paragraph(right_html, right_style)
    t = Table([[left, right]], colWidths=[CONTENT_W * 0.705, CONTENT_W * 0.295])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    t.spaceBefore = space_before
    return t


def _heading(text, s, f=1.0):
    # Sections get the largest gap in the document -- that contrast is what
    # separates "typeset" from "uniformly spaced".
    return SectionHeading(text, size=8.6 * f, tracking=1.55, gap_to_rule=3.4,
                           space_before=10.5 * s, space_after=5.2 * s)


def _build_story(profile: dict, content: dict, s: float, f: float = 1.0) -> list:
    st = _styles(s, f)
    story = []

    story.append(Paragraph(_esc(profile.get("name", "")), st["name"]))

    contact_bits = [_esc(profile.get("location", ""))]
    if profile.get("phone"):
        contact_bits.append(_esc(profile["phone"]))
    email = profile.get("email", "")
    if email:
        contact_bits.append(f'<a href="mailto:{email}"><u>{_esc(email)}</u></a>')
    links = profile.get("links", {})
    for label, key in (("LinkedIn", "linkedin"), ("GitHub", "github"),
                       ("Hugging Face", "huggingface"), ("Website", "portfolio")):
        if links.get(key):
            contact_bits.append(_link(label, links[key], underline=True))
    story.append(Paragraph("  &#183;  ".join(contact_bits), st["contact"]))
    story.append(HeaderRule(space_before=6.5 * s, space_after=0))

    education = profile.get("education", {})
    if education:
        story.append(_heading("Education", s, f))
        gpa = f' &#183; GPA {education["gpa"]}' if education.get("gpa") else ""
        block = [
            _two_col(f'{_esc(education.get("school", ""))}', "", st["org"], st["right"]),
            _two_col(f'{_esc(education.get("degree", ""))}{gpa}',
                     _esc(education.get("graduated", "")), st["role"], st["right_italic"]),
        ]
        story.append(KeepTogether(block))

    if content.get("summary"):
        story.append(_heading("Summary", s, f))
        story.append(Paragraph(_no_widow(_esc(content["summary"])), st["body"]))

    experience = content.get("experience", [])
    if experience:
        story.append(_heading("Experience", s, f))
        for i, entry in enumerate(experience):
            org = entry.get("org", "")
            block = [
                _two_col(_link(org, ENTRY_LINKS.get(org)), _esc(entry.get("location", "")),
                         st["org"], st["right"], space_before=(6.5 * s if i else 0)),
                _two_col(_esc(entry.get("title", "")), _esc(entry.get("dates", "")),
                         st["role"], st["right_italic"]),
            ]
            bullets = [_clean_bullet(b) for b in entry.get("bullets", [])]
            for bullet in [b for b in bullets if b][:MAX_BULLETS_PER_EXPERIENCE]:
                block.append(Paragraph(_no_widow(_esc(bullet)), st["bullet"], bulletText="•"))
            story.append(KeepTogether(block))

    projects = content.get("projects", [])
    if projects:
        story.append(_heading("Projects", s, f))
        for i, proj in enumerate(projects[:MAX_PROJECTS]):
            block = [
                _two_col(_link(proj.get("name", ""), proj.get("link")),
                         _esc(proj.get("dates", "")), st["org"], st["right_italic"],
                         space_before=(6.5 * s if i else 0)),
            ]
            bullets = [_clean_bullet(b) for b in proj.get("bullets", [])]
            for bullet in [b for b in bullets if b][:MAX_BULLETS_PER_PROJECT]:
                block.append(Paragraph(_no_widow(_esc(bullet)), st["bullet"], bulletText="•"))
            story.append(KeepTogether(block))

    if content.get("skills_line"):
        story.append(_heading("Skills", s, f))
        story.append(Paragraph(_no_widow(_esc(content["skills_line"])), st["body"]))

    certs = profile.get("certifications_earned", [])
    if certs:
        story.append(_heading("Certifications", s, f))
        story.append(Paragraph(_no_widow(_esc(", ".join(certs[:6]))), st["body"]))

    return story


def bullet_line_count(text: str) -> int:
    """How many rendered lines a bullet takes at the body measure. Used to
    flag 3+ line bullets, which read as unedited wall-of-text -- they're
    reported, never silently truncated, since trimming real content is a
    content decision (the tailoring prompt's job), not a rendering one."""
    st = _styles(1.0)["bullet"]
    p = Paragraph(_no_widow(_esc(_clean_bullet(text))), st, bulletText="•")
    _, h = p.wrap(CONTENT_W - st.leftIndent, 1000)
    return max(1, round(h / st.leading))


def _overlong_bullets(content: dict) -> list[str]:
    out = []
    for entry in content.get("experience", []):
        for b in entry.get("bullets", [])[:MAX_BULLETS_PER_EXPERIENCE]:
            if b and bullet_line_count(b) >= 3:
                out.append(b)
    for proj in content.get("projects", [])[:MAX_PROJECTS]:
        for b in proj.get("bullets", [])[:MAX_BULLETS_PER_PROJECT]:
            if b and bullet_line_count(b) >= 3:
                out.append(b)
    return out


def _doc(target):
    return SimpleDocTemplate(
        target, pagesize=LETTER,
        topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        title="Resume", author="",
    )


def _pages_at(profile, content, s, f) -> int:
    buf = io.BytesIO()
    doc = _doc(buf)
    doc.build(_build_story(profile, content, s, f))
    return doc.page


def render_resume_pdf(out_path: str, profile: dict, content: dict) -> dict:
    """Renders the resume at the most generous type size and spacing that
    still fits one page, so short content fills the page instead of
    trailing off and long content tightens instead of spilling to page two.

    Searches type size first (bigger type reads better than bigger gaps),
    then spacing, taking the first combination that fits."""
    # For a fixed type size, fitting is monotonic in spacing -- if a roomy
    # layout fits, every tighter one does too. So find the roomiest spacing
    # per type size, then pick between those.
    best_per_size = []
    for f in (1.08, 1.04, 1.0, 0.96):
        for s in (1.45, 1.3, 1.15, 1.0, 0.9, 0.82, 0.74):
            if _pages_at(profile, content, s, f) == 1:
                best_per_size.append((f, s))
                break

    if best_per_size:
        # Section rhythm matters more than raw type size -- a page with big
        # text but no air between sections reads worse than slightly smaller
        # text that's properly grouped. So only consider layouts that keep
        # near-full spacing, and among those take the largest type.
        roomy = [c for c in best_per_size if c[1] >= 0.95]
        chosen_f, chosen_s = max(roomy or best_per_size, key=lambda c: (c[0], c[1]))
    else:
        chosen_s, chosen_f = 0.74, 0.96  # render anyway; caller sees pages > 1

    doc = _doc(out_path)
    doc.build(_build_story(profile, content, chosen_s, chosen_f))
    chosen = chosen_s
    return {
        "pages": doc.page,
        "spacing_scale": chosen,
        "type_scale": chosen_f,
        # Below 0.95 the fit pass had to sacrifice section rhythm to stay on
        # one page -- a signal the content is too long, not that the layout
        # is wrong. Surfaced so it's visible rather than silently cramped.
        "layout_cramped": chosen < 0.95,
        "overlong_bullets": _overlong_bullets(content),
    }
