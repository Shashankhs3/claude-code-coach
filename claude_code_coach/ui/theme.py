"""Application-wide stylesheet — light theme, dark sidebar (Executive-
Dashboard/data-tool style: large KPI numbers, status-colored left borders,
neutral surfaces, one warm accent). Refined pass (see git history around
this file's last change): normalized spacing/radius scale, real card
elevation via QGraphicsDropShadowEffect (QSS alone can't do box-shadow),
and — the biggest visible gap before this pass — QCheckBox/QComboBox had
NO rules at all here and were rendering as plain OS-native Windows
controls against an otherwise fully custom theme. Colors keep the app's
existing warm-terracotta identity rather than a rebrand; contrast was
rechecked against WCAG AA (4.5:1 body text) while doing so.

UI stabilization pass (docs/UI_STABILIZATION_AUDIT.md, Issues 3/4): the
blanket `QWidget { background: ... }` rule below was removed — Qt paints
that as an opaque rectangle behind *every* widget once any app-wide
stylesheet is active, including plain QLabels sitting inside a white
#Card/#Panel, which is exactly where the "grey box behind every value"
symptom came from. Every widget that should actually show a surface still
has its own explicit rule (QMainWindow, #Sidebar, #Card, #Panel, inputs,
etc.) — nothing lost a background it was supposed to have. Every
`cursor: pointer;` declaration was also removed: Qt Style Sheets do not
support the CSS `cursor` property at all (confirmed via
QT_FORCE_STDERR_LOGGING=1: it printed "Unknown property cursor" once per
matching rule application) — the pointer-cursor UX this docstring used to
promise is restored properly via `widgets.PointerCursorFilter`, a small
Qt event filter installed once on the QApplication in app.py, instead of
an invalid QSS property.
"""

# -- Spacing / radius scale (8px base unit, matches this app's own grid) ---
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 16
SPACE_LG = 24
RADIUS_SM = 6
RADIUS_MD = 10
RADIUS_LG = 14

# -- Palette ---------------------------------------------------------------
BG = "#f5f6f8"
SIDEBAR_BG = "#15171c"
SIDEBAR_HOVER = "#22252d"
SIDEBAR_ACTIVE = "#c1602f"
CARD_BG = "#ffffff"
BORDER = "#e2e4e8"
BORDER_STRONG = "#cbd0d8"
INPUT_BG = "#ffffff"

TEXT_PRIMARY = "#1a1d23"
# Darkened from the previous #6b7280 (~4.6:1 on white — technically AA but
# with almost no margin) to a safer, still-clearly-"muted" tone.
TEXT_MUTED = "#5a616e"
TEXT_FAINT = "#9aa1ac"
TEXT_ON_DARK = "#e7e9ee"
TEXT_ON_DARK_MUTED = "#9096a1"

ACCENT = "#c1602f"
ACCENT_STRONG = "#a94f24"
ACCENT_SOFT = "#fbeee6"
BUTTON_BG = "#20232a"
BUTTON_HOVER = "#30343d"
BUTTON_PRESSED = "#14161a"

GOOD = "#1e8e5a"
WARN = "#b7791f"
BAD = "#c0392b"
INFO = "#2563eb"

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Cascadia Code", Arial, sans-serif;
}}

QWidget {{
    color: {TEXT_PRIMARY};
    font-size: 13px;
}}

QMainWindow {{
    background: {BG};
}}

QToolTip {{
    background: {SIDEBAR_BG};
    color: {TEXT_ON_DARK};
    border: 1px solid #2c3038;
    border-radius: {RADIUS_SM}px;
    padding: 6px 10px;
    font-size: 12px;
}}

#Sidebar {{
    background: {SIDEBAR_BG};
    border-right: 1px solid #0c0d10;
}}

#Logo {{
    color: #ffffff;
    font-size: 17px;
    font-weight: 700;
    padding: 22px 18px 4px 18px;
    background: transparent;
}}

#LogoSub {{
    color: {TEXT_ON_DARK_MUTED};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 0 18px 18px 18px;
    background: transparent;
}}

#NavButton {{
    text-align: left;
    padding: 10px 16px;
    border: none;
    border-radius: {RADIUS_SM}px;
    color: #c7cbd3;
    background: transparent;
    font-size: 13px;
    margin: 1px 10px;
}}

#NavButton:hover {{
    background: {SIDEBAR_HOVER};
    color: #f0a878;
}}

#NavButton:checked, #NavButton:checked:hover {{
    background: {SIDEBAR_ACTIVE};
    color: #ffffff;
    font-weight: 600;
}}

#Privacy {{
    color: {TEXT_ON_DARK_MUTED};
    font-size: 10.5px;
    padding: 12px 16px;
    border-top: 1px solid #232733;
    background: transparent;
}}

#PageTitle {{
    font-size: 24px;
    font-weight: 700;
    color: {TEXT_PRIMARY};
}}

#PageSubtitle {{
    color: {TEXT_MUTED};
    font-size: 12.5px;
    padding-bottom: 6px;
}}

#SectionHeader {{
    color: #444a56;
    font-size: 12.5px;
    font-weight: 700;
    letter-spacing: 0.5px;
    padding-top: 6px;
}}

#Card {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
}}

#CardTitle {{
    color: #8a909c;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.6px;
}}

#CardValue {{
    font-size: 28px;
    font-weight: 800;
    color: {TEXT_PRIMARY};
}}

#CardSubtitle {{
    color: {TEXT_MUTED};
    font-size: 11px;
}}

#Panel {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
}}

#EmptyState {{
    color: {TEXT_MUTED};
    font-size: 13px;
    padding: 30px;
}}

QTextEdit, QLineEdit {{
    background: {INPUT_BG};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 10px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
    selection-color: white;
}}

QTextEdit:hover, QLineEdit:hover {{
    border: 1px solid {BORDER_STRONG};
}}

QTextEdit:focus, QLineEdit:focus {{
    border: 1px solid {ACCENT};
}}

QPushButton {{
    background: {BUTTON_BG};
    color: white;
    border: none;
    border-radius: {RADIUS_SM}px;
    padding: 9px 18px;
    font-weight: 600;
}}

QPushButton:hover {{
    background: {BUTTON_HOVER};
}}

QPushButton:pressed {{
    background: {BUTTON_PRESSED};
}}

QPushButton:disabled {{
    background: #cfd3d9;
    color: #8b909a;
}}

QPushButton#Secondary {{
    background: #ffffff;
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
}}

QPushButton#Secondary:hover {{
    background: #eef0f3;
    border: 1px solid {BORDER_STRONG};
}}

QPushButton#Danger {{
    background: {BAD};
    color: white;
}}

QPushButton#Danger:hover {{
    background: #a8341f;
}}

QCheckBox, QRadioButton {{
    color: {TEXT_PRIMARY};
    spacing: 8px;
    padding: 2px 0;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 17px;
    height: 17px;
    border: 1px solid {BORDER_STRONG};
    background: {CARD_BG};
}}

QCheckBox::indicator {{
    border-radius: 4px;
}}

QRadioButton::indicator {{
    border-radius: 9px;
}}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border: 1px solid {ACCENT};
}}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
}}

QComboBox {{
    background: {INPUT_BG};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 7px 12px;
    color: {TEXT_PRIMARY};
}}

QComboBox:hover {{
    border: 1px solid {BORDER_STRONG};
}}

QComboBox:focus {{
    border: 1px solid {ACCENT};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM}px;
    outline: none;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {ACCENT_STRONG};
    padding: 4px;
}}

QListWidget {{
    background: #ffffff;
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 4px;
    outline: none;
}}

QListWidget::item {{
    padding: 10px 8px;
    border-radius: {RADIUS_SM}px;
    color: {TEXT_PRIMARY};
}}

QListWidget::item:selected {{
    background: {ACCENT_SOFT};
    color: {ACCENT_STRONG};
}}

QListWidget::item:hover {{
    background: #f2f3f5;
}}

QProgressBar {{
    background: #eceef1;
    border: none;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 6px;
}}

QScrollArea {{
    border: none;
    background: transparent;
}}

/* The sidebar's nav list scroll area, its internal viewport, and the
   content widget it holds (three separate widgets — see main_window.py's
   _build_sidebar for the exact hierarchy and why each needs its own rule
   here) all painted dark instead of transparent, so the sidebar's own
   dark background actually reaches the nav buttons rather than each of
   these defaulting to an opaque OS-palette background. */
QScrollArea#NavScroll {{
    background: transparent;
    border: none;
}}

#NavViewport, #NavContent {{
    background: {SIDEBAR_BG};
}}

/* Workshop Mode's course-map list — same fix, same reason, light-page
   version: see ui/workshop.py's _CourseMap. */
QScrollArea#WorkshopMapScroll {{
    background: transparent;
    border: none;
}}

#WorkshopMapViewport, #WorkshopMapContent {{
    background: {BG};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 11px;
    margin: 2px;
}}

QScrollBar::handle:vertical {{
    background: #c7cbd3;
    min-height: 28px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical:hover {{
    background: #aeb3bd;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 11px;
    margin: 2px;
}}

QScrollBar::handle:horizontal {{
    background: #c7cbd3;
    min-width: 28px;
    border-radius: 5px;
}}

QScrollBar::handle:horizontal:hover {{
    background: #aeb3bd;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
    border: none;
    background: none;
}}

QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

QSplitter::handle {{
    background: {BORDER};
}}

QLabel#Badge {{
    border-radius: 5px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}}

QLabel#ScoreValue {{
    font-size: 42px;
    font-weight: 800;
}}

QLabel#RatingLabel {{
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.6px;
}}

QMessageBox {{
    background: {CARD_BG};
}}
"""


def rating_color(rating: str) -> str:
    return {
        "EXCELLENT": GOOD,
        "GOOD": GOOD,
        "NEEDS IMPROVEMENT": WARN,
        "POOR": BAD,
    }.get(rating.upper(), INFO)


def badge_style(color: str) -> str:
    return f"background: {color}1f; color: {color}; border: 1px solid {color}55;"


def status_border_style(color: str, *, radius: int = RADIUS_MD) -> str:
    """A complete, self-sufficient stylesheet for a Panel/Card-like
    QFrame that also carries a left-border status accent — cheap,
    scannable "this section needs attention" signal (Executive Dashboard
    pattern: status conveyed by a colored border, not by re-tinting the
    whole surface).

    Returns a full stylesheet (background/border/radius included), not a
    delta to append to the widget's existing #Panel-objectName style: Qt's
    style-sheet cascade does not reliably merge a `border-left` set via
    `setStyleSheet()` with a `border` shorthand coming from a different
    (application-level) stylesheet for the same widget. Use as
    ``widget.setStyleSheet(status_border_style(color))``, replacing
    whatever style that instance had.
    """
    return (
        f"background: {CARD_BG}; "
        f"border: 1px solid {BORDER}; "
        f"border-left: 3px solid {color}; "
        f"border-radius: {radius}px;"
    )
