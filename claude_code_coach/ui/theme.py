"""Application-wide stylesheet — light theme, matching the earlier
prototype's high-contrast look (white cards, near-black sidebar) but
refined: consistent spacing, badges, and a score-aware color system.
"""

# -- Palette ---------------------------------------------------------------
BG = "#f5f6f8"
SIDEBAR_BG = "#15171c"
SIDEBAR_HOVER = "#22252d"
CARD_BG = "#ffffff"
BORDER = "#e2e4e8"
INPUT_BG = "#ffffff"

TEXT_PRIMARY = "#1a1d23"
TEXT_MUTED = "#6b7280"
TEXT_FAINT = "#9aa1ac"
TEXT_ON_DARK = "#e7e9ee"
TEXT_ON_DARK_MUTED = "#9096a1"

ACCENT = "#c1602f"
ACCENT_STRONG = "#a94f24"
BUTTON_BG = "#20232a"
BUTTON_HOVER = "#30343d"
BUTTON_PRESSED = "#14161a"

GOOD = "#1e8e5a"
WARN = "#b7791f"
BAD = "#c0392b"
INFO = "#2b6cb0"

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Cascadia Code", Arial, sans-serif;
}}

QWidget {{
    background: {BG};
    color: {TEXT_PRIMARY};
    font-size: 13px;
}}

QMainWindow {{
    background: {BG};
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
    border-radius: 8px;
    color: #c7cbd3;
    background: transparent;
    font-size: 13px;
    margin: 1px 10px;
}}

#NavButton:hover {{
    background: {SIDEBAR_HOVER};
    color: white;
}}

#NavButton:checked {{
    background: #2a2320;
    color: #e8935f;
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
    border-radius: 10px;
}}

#CardTitle {{
    color: #8a909c;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.6px;
}}

#CardValue {{
    font-size: 26px;
    font-weight: 700;
    color: {TEXT_PRIMARY};
}}

#CardSubtitle {{
    color: {TEXT_MUTED};
    font-size: 11px;
}}

#Panel {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

#EmptyState {{
    color: {TEXT_MUTED};
    font-size: 13px;
    padding: 30px;
}}

QTextEdit, QLineEdit {{
    background: {INPUT_BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 10px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
    selection-color: white;
}}

QTextEdit:focus, QLineEdit:focus {{
    border: 1px solid {ACCENT};
}}

QPushButton {{
    background: {BUTTON_BG};
    color: white;
    border: none;
    border-radius: 8px;
    padding: 9px 18px;
    font-weight: 600;
}}

QPushButton:hover {{
    background: {BUTTON_HOVER};
}}

QPushButton:pressed {{
    background: {BUTTON_PRESSED};
}}

QPushButton#Secondary {{
    background: #ffffff;
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
}}

QPushButton#Secondary:hover {{
    background: #eef0f3;
}}

QPushButton#Danger {{
    background: {BAD};
    color: white;
}}

QPushButton#Danger:hover {{
    background: #a8341f;
}}

QListWidget {{
    background: #ffffff;
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 4px;
    outline: none;
}}

QListWidget::item {{
    padding: 10px 8px;
    border-radius: 6px;
    color: {TEXT_PRIMARY};
}}

QListWidget::item:selected {{
    background: #fbeee6;
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
