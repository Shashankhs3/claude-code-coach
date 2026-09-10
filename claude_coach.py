
import sys
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QListWidget, QListWidgetItem,
    QStackedWidget, QFrame, QMessageBox, QProgressBar, QSplitter
)

APP_DIR = Path.home() / ".claude_code_coach"
APP_DIR.mkdir(exist_ok=True)
DB = APP_DIR / "coach.db"


# ---------------- Database ----------------

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            prompt TEXT NOT NULL,
            score INTEGER NOT NULL,
            rating TEXT NOT NULL,
            good_count INTEGER NOT NULL,
            warning_count INTEGER NOT NULL,
            opportunities TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


# ---------------- Analyzer ----------------

def has(text, patterns):
    return any(re.search(p, text, re.I) for p in patterns)


def analyze(prompt):
    """
    V2.1 heuristic analyzer.

    Important design principle:
    - Detect meaningful evidence, not just action keywords.
    - "Missing" is not automatically "bad".
    - Simple information requests should not be penalized for lacking
      implementation-style fields such as a definition of done.
    """
    p = prompt.strip()
    low = p.lower()

    result = {
        "score": 0,
        "rating": "",
        "good": [],
        "warnings": [],
        "opportunities": [],
    }

    if not p:
        result["score"] = 0
        result["rating"] = "POOR"
        result["warnings"].append("Prompt is empty.")
        return result

    # ---- Intent classification ------------------------------------------------
    question_like = bool(re.search(
        r"^(what|why|how|where|which|who|when|can you explain|"
        r"show me|tell me|is there|does)\b", low
    )) or p.endswith("?")

    informational = question_like and not bool(re.search(
        r"\b(add|create|build|implement|modify|change|fix|refactor|remove|"
        r"update|delete|rewrite|migrate|debug|investigate|optimi[sz]e|review)\b",
        low
    ))

    implementation = bool(re.search(
        r"\b(add|create|build|implement|modify|change|fix|refactor|remove|"
        r"update|delete|rewrite|migrate|debug|investigate|optimi[sz]e|"
        r"improve|review|audit)\b", low
    ))

    # ---- Goal quality ---------------------------------------------------------
    vague_goal_patterns = [
        r"^\s*(fix|improve|change|update|clean up|make better)\s+(my|the)\s+"
        r"(project|app|application|code|repo|repository)\s*[\.\!]*\s*$",
        r"^\s*(make|do)\s+(it|this)\s+(better|good|properly)\s*[\.\!]*\s*$",
        r"^\s*(fix|improve)\s+everything\s*[\.\!]*\s*$",
        r"^\s*make\s+the\s+(project|app|application|code)\s+better\s*[\.\!]*\s*$",
    ]

    explicit_goal = False
    vague_goal = any(re.match(x, p, re.I) for x in vague_goal_patterns)

    # A meaningful object/problem/outcome after the action is stronger evidence
    # than merely finding an action verb.
    if implementation and not vague_goal:
        explicit_goal = bool(re.search(
            r"\b(login|auth|authentication|authorization|checkout|payment|"
            r"api|endpoint|database|db|test|bug|error|500|timeout|memory|"
            r"performance|security|validation|logging|ui|frontend|backend|"
            r"component|route|middleware|webhook|cache|caching|migration|"
            r"deployment|ci|build|dependency|token|password|reset|"
            r"rate.?limit|n\+1|query|leak|failure|failing)\b", low
        ))

        # Concrete nouns, paths, quoted terms, or an explicit "why" problem
        # also count as goal evidence.
        if re.search(r"(src/|tests?/|app/|lib/|\.py\b|\.ts\b|\.tsx\b|\.js\b|"
                     r"\.jsx\b|\.java\b|\.go\b|\.rs\b|`[^`]+`|"
                     r"\bwhy\b.*\b(return|fail|break|crash|error|timeout)\b)",
                     low):
            explicit_goal = True

        # Longer prompts with a concrete requested outcome are generally clear.
        if len(p.split()) >= 8 and re.search(
            r"\b(returns?|fails?|crashes?|throws?|stores?|uses?|"
            r"contains?|handles?|identify|locate|trace|add|remove|"
            r"produce|return|report|summarize)\b", low
        ):
            explicit_goal = True

    if informational:
        result["good"].append("Clear information request detected.")
    elif explicit_goal:
        result["good"].append("Clear, actionable goal detected.")
    elif vague_goal:
        result["warnings"].append(
            "Goal is too vague — the requested outcome or problem is not identified."
        )
    elif implementation:
        result["warnings"].append(
            "An action is requested, but the specific problem or outcome is unclear."
        )
    else:
        result["warnings"].append(
            "No clear task or information goal detected."
        )

    # ---- Scope ----------------------------------------------------------------
    has_path = bool(re.search(
        r"(^|[\s`'\"(])(src|app|lib|tests?|docs|packages?|components?|"
        r"services?|server|client|backend|frontend)[/\\]|"
        r"\b[\w./\\-]+\.(py|js|jsx|ts|tsx|java|go|rs|cs|cpp|c|sql|md|json|yaml|yml)\b",
        p, re.I
    ))
    has_scope_language = bool(re.search(
        r"\b(only|just|focus on|within|under|in|from|related to|"
        r"affected|relevant)\b.{0,60}\b(code|files?|folder|directory|module|"
        r"package|component|auth|authentication|payment|checkout|api|"
        r"database|db|backend|frontend|module)\b", low
    ))

    if has_path or has_scope_language:
        result["good"].append("Scope is bounded or relevant files/directories are identified.")
    elif implementation and not vague_goal:
        result["opportunities"].append(
            "Consider specifying relevant files/directories."
        )
    elif vague_goal:
        # Keep the message concise; scope is one of the fundamental missing pieces.
        result["warnings"].append("No scope is specified.")

    # ---- Search / investigation strategy ------------------------------------
    has_search = bool(re.search(
        r"\b(search|grep|find|locate|trace|inspect|investigate|reproduce|"
        r"look for|trace through|start by locating|check the relevant)\b", low
    ))
    has_read_broadly = bool(re.search(
        r"\b(entire|whole|all|every|everything|full)\s+"
        r"(repo|repository|project|codebase|files?|application)\b", low
    ))

    if has_search:
        result["good"].append("Investigation/search strategy is specified.")
    elif has_read_broadly:
        result["warnings"].append(
            "The prompt asks for broad reading; search/narrow first where possible."
        )
    elif implementation and not vague_goal:
        result["opportunities"].append(
            "Consider searching/tracing before reading large amounts of code."
        )

    # ---- Constraints ----------------------------------------------------------
    has_constraints = bool(re.search(
        r"\b(don't|do not|must|should not|avoid|only|reuse|smallest|"
        r"minimal|without|keep|preserve|unrelated|existing conventions|"
        r"production|read.?only|no changes?)\b", low
    ))
    if has_constraints:
        result["good"].append("Useful constraints are specified.")
    elif implementation and explicit_goal:
        result["opportunities"].append(
            "Consider adding constraints, such as what not to change or conventions to preserve."
        )

    # ---- Definition of done ---------------------------------------------------
    has_done = bool(re.search(
        r"\b(done when|complete when|success when|success criteria|"
        r"acceptance criteria|expected result|tests? pass|should pass|"
        r"verify that|confirm that)\b", low
    ))
    if has_done:
        result["good"].append("Definition of done or verification criteria detected.")
    elif implementation and explicit_goal:
        result["opportunities"].append(
            "Add a clear 'Done when...' condition."
        )

    # ---- Output control -------------------------------------------------------
    has_output_control = bool(re.search(
        r"\b(return|output|give me|summari[sz]e|report|format|"
        r"only|top \d+|one sentence|bullet|table|checklist)\b", low
    ))
    if has_output_control:
        result["good"].append("Output expectations are reasonably controlled.")
    elif informational:
        result["opportunities"].append(
            "Consider specifying the level/format of detail you want."
        )

    # ---- Excessive / conflicting breadth -------------------------------------
    breadth = 0
    if re.search(r"\b(entire|whole|everything|all|every)\b", low):
        breadth += 1
    if re.search(r"\b(perfect|all possible|from every angle|whatever you think|"
                 r"anything|everything you find)\b", low):
        breadth += 1
    if len(p.split()) > 80:
        breadth += 1
    if breadth >= 2:
        result["warnings"].append(
            "Task is unusually broad; narrow the scope to reduce unnecessary context."
        )

    # ---- Skill / Agent / CLAUDE.md opportunities -----------------------------
    # These are suggestions, not failures.
    workflow_markers = len(re.findall(
        r"\b(every time|for every|each time|always|same checklist|"
        r"repeat|repeatedly|for every pr|for every pull request)\b", low
    ))
    checklist_markers = len(re.findall(
        r"\b(first|then|finally|check|review|inspect|identify|produce|"
        r"validate|verify)\b", low
    ))
    if workflow_markers >= 1 and checklist_markers >= 2:
        result["opportunities"].append(
            "This looks like a repeatable workflow — consider creating or using a Skill."
        )

    independent_investigation = (
        len(re.findall(
            r"\b(investigate|trace|compare|analy[sz]e|diagnose|identify)\b", low
        )) >= 2
        and len(p.split()) >= 25
    )
    if independent_investigation:
        result["opportunities"].append(
            "This is a substantial independent investigation — an Agent/subagent may be useful."
        )

    persistent_rule = bool(re.search(
        r"\b(every time|always|must|never)\b", low
    )) and bool(re.search(
        r"\b(project|api|database|migration|production|configuration|"
        r"tests?|security|logging|convention|rule)\b", low
    ))
    if persistent_rule:
        result["opportunities"].append(
            "This sounds like a persistent project rule — consider putting it in CLAUDE.md."
        )

    # ---- Context management ---------------------------------------------------
    context_heavy = bool(re.search(
        r"\b(everything we've discussed|entire conversation|whole conversation|"
        r"re.?read everything|all previous|from the beginning|huge|long session)\b",
        low
    ))
    if context_heavy:
        result["opportunities"].append(
            "Context may be noisy or larger than necessary — consider narrowing the task or using /compact."
        )

    # ---- Scoring --------------------------------------------------------------
    # Score dimensions independently. Missing implementation-only dimensions
    # are not penalized for simple information requests.
    score = 100

    if vague_goal:
        score -= 35
    elif implementation and not explicit_goal:
        score -= 25

    if implementation and not (has_path or has_scope_language):
        score -= 15

    if implementation and explicit_goal and not has_search:
        score -= 5

    if implementation and explicit_goal and not has_constraints:
        score -= 5

    if implementation and explicit_goal and not has_done:
        score -= 10

    if implementation and explicit_goal and has_read_broadly:
        score -= 10

    if breadth >= 2:
        score -= 10

    score = max(0, min(100, score))

    if score >= 85:
        rating = "EXCELLENT"
    elif score >= 70:
        rating = "GOOD"
    elif score >= 45:
        rating = "NEEDS IMPROVEMENT"
    else:
        rating = "POOR"

    result["score"] = score
    result["rating"] = rating

    # For an extremely vague task, surface the most useful coaching points.
    if vague_goal:
        result["opportunities"] = [
            "State what is broken or what outcome you want.",
            "Specify relevant files/directories or the area to investigate.",
            "Add a clear 'Done when...' condition.",
        ]

    # Avoid overloading users with duplicate/near-duplicate messages.
    def dedupe(items):
        out = []
        seen = set()
        for item in items:
            key = item.lower()
            if key not in seen:
                seen.add(key)
                out.append(item)
        return out

    result["good"] = dedupe(result["good"])
    result["warnings"] = dedupe(result["warnings"])
    result["opportunities"] = dedupe(result["opportunities"])
    return result

def card(title, value, subtitle=""):
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    t = QLabel(title)
    t.setObjectName("CardTitle")
    v = QLabel(value)
    v.setObjectName("CardValue")
    s = QLabel(subtitle)
    s.setObjectName("CardSubtitle")
    layout.addWidget(t)
    layout.addWidget(v)
    layout.addWidget(s)
    return frame


class Dashboard(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        layout = QVBoxLayout(self)

        title = QLabel("Dashboard")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        self.cards = QHBoxLayout()
        layout.addLayout(self.cards)

        self.content = QLabel()
        self.content.setWordWrap(True)
        self.content.setObjectName("DashboardText")
        layout.addWidget(self.content)
        layout.addStretch()

        self.refresh()

    def refresh(self):
        for i in reversed(range(self.cards.count())):
            item = self.cards.takeAt(i)
            if item.widget():
                item.widget().deleteLater()

        conn = db()
        rows = conn.execute("SELECT * FROM prompts ORDER BY id DESC").fetchall()
        conn.close()

        count = len(rows)
        avg = round(sum(r["score"] for r in rows) / count) if count else 0
        good = sum(r["good_count"] for r in rows)
        warnings = sum(r["warning_count"] for r in rows)

        self.cards.addWidget(card("PROMPTS", str(count), "analysed locally"))
        self.cards.addWidget(card("AVG SCORE", f"{avg}/100", "prompt habit score"))
        self.cards.addWidget(card("GOOD HABITS", str(good), "detected"))
        self.cards.addWidget(card("WARNINGS", str(warnings), "detected"))

        if not rows:
            self.content.setText(
                "Welcome to Claude Code Coach V2.\n\n"
                "Paste a Claude Code prompt in Prompt Inspector to begin.\n\n"
                "The app stores prompt history locally in SQLite so it can "
                "eventually detect repeated workflows, Skills opportunities, "
                "Agent opportunities and context habits."
            )
        else:
            self.content.setText(
                "Your coach is learning from this local session history.\n\n"
                "Next V2 milestone: compare prompts over time and identify "
                "repeatable workflows that could become Skills or persistent "
                "CLAUDE.md guidance."
            )


class Inspector(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app

        layout = QVBoxLayout(self)

        title = QLabel("Prompt Inspector")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        self.editor = QTextEdit()
        self.editor.setPlaceholderText(
            "Paste a Claude Code prompt here...\n\n"
            "Example:\n"
            "Find where the login request is handled.\n"
            "Only inspect src/auth/.\n"
            "Identify the root cause before modifying files.\n"
            "Done when the authentication tests pass.\n"
            "Return only root cause, changed files and test result."
        )
        layout.addWidget(self.editor)

        self.analyze_button = QPushButton("Analyze Prompt")
        self.analyze_button.clicked.connect(self.run_analysis)
        layout.addWidget(self.analyze_button)

        self.result = QTextEdit()
        self.result.setReadOnly(True)
        layout.addWidget(self.result)

    def run_analysis(self):
        prompt = self.editor.toPlainText().strip()

        if not prompt:
            QMessageBox.warning(self, "No prompt", "Paste a prompt first.")
            return

        score, rating, good, warnings, opportunities = analyze(prompt)

        conn = db()
        conn.execute(
            """
            INSERT INTO prompts
            (created_at, prompt, score, rating, good_count, warning_count, opportunities)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                prompt,
                score,
                rating,
                len(good),
                len(warnings),
                "\n".join(opportunities),
            ),
        )
        conn.commit()
        conn.close()

        output = [
            f"SCORE: {score}/100",
            f"RATING: {rating}",
            "",
        ]

        if good:
            output.append("🟢 GOOD HABITS")
            for item in good:
                output.append(f"✓ {item}")
            output.append("")

        if warnings:
            output.append("🟡 IMPROVEMENTS")
            for item in warnings:
                output.append(f"⚠ {item}")
            output.append("")

        if opportunities:
            output.append("🔵 OPPORTUNITIES")
            for item in opportunities:
                output.append(f"→ {item}")
            output.append("")

        output.append(
            "Note: V2 uses local heuristics. "
            "The score is not an official Claude/Anthropic metric "
            "and does not measure actual token savings."
        )

        self.result.setPlainText("\n".join(output))
        self.app.dashboard.refresh()
        self.app.history.refresh()


class History(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app

        layout = QVBoxLayout(self)

        title = QLabel("Prompt History")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        splitter = QSplitter(Qt.Horizontal)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self.show_item)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)

        splitter.addWidget(self.list)
        splitter.addWidget(self.detail)
        splitter.setSizes([360, 700])

        layout.addWidget(splitter)

        self.refresh()

    def refresh(self):
        self.list.clear()

        conn = db()
        rows = conn.execute(
            "SELECT * FROM prompts ORDER BY id DESC"
        ).fetchall()
        conn.close()

        for row in rows:
            preview = row["prompt"].replace("\n", " ")[:70]
            item = QListWidgetItem(
                f'{row["score"]}/100  •  {preview}'
            )
            item.setData(Qt.UserRole, row["id"])
            self.list.addItem(item)

    def show_item(self, current, previous):
        if not current:
            return

        row_id = current.data(Qt.UserRole)

        conn = db()
        row = conn.execute(
            "SELECT * FROM prompts WHERE id = ?",
            (row_id,)
        ).fetchone()
        conn.close()

        if not row:
            return

        score, rating, good, warnings, opportunities = analyze(row["prompt"])

        text = [
            f"Score: {score}/100",
            f"Rating: {rating}",
            f"Time: {row['created_at']}",
            "",
            "PROMPT",
            "──────",
            row["prompt"],
            "",
            "ANALYSIS",
            "────────",
        ]

        if good:
            text.append("\nGOOD HABITS")
            text.extend(f"✓ {x}" for x in good)

        if warnings:
            text.append("\nIMPROVEMENTS")
            text.extend(f"⚠ {x}" for x in warnings)

        if opportunities:
            text.append("\nOPPORTUNITIES")
            text.extend(f"→ {x}" for x in opportunities)

        self.detail.setPlainText("\n".join(text))


class Habits(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app

        layout = QVBoxLayout(self)

        title = QLabel("Habits")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        self.text = QLabel()
        self.text.setWordWrap(True)
        layout.addWidget(self.text)

        self.refresh()

    def refresh(self):
        conn = db()
        rows = conn.execute("SELECT * FROM prompts").fetchall()
        conn.close()

        if not rows:
            self.text.setText("No data yet. Analyze some prompts first.")
            return

        scores = [r["score"] for r in rows]
        avg = round(sum(scores) / len(scores))

        skill = sum(
            1 for r in rows
            if "Skill" in r["opportunities"]
        )

        agent = sum(
            1 for r in rows
            if "Agent" in r["opportunities"]
        )

        md = sum(
            1 for r in rows
            if "CLAUDE.md" in r["opportunities"]
        )

        self.text.setText(
            f"Average prompt score: {avg}/100\n\n"
            f"🧩 Skill opportunities: {skill}\n"
            f"🤖 Agent opportunities: {agent}\n"
            f"📄 CLAUDE.md opportunities: {md}\n\n"
            "These are opportunity signals, not proof that a Skill, "
            "Agent or CLAUDE.md entry is required."
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Claude Code Coach V2")
        self.resize(1200, 760)

        central = QWidget()
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)

        # Sidebar
# Sidebar
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(210)

        side = QVBoxLayout(sidebar)

        logo = QLabel("CLAUDE\nCODE COACH")
        logo.setObjectName("Logo")
        side.addWidget(logo)

        self.buttons = []

        for name in [
            "Dashboard",
            "Prompt Inspector",
            "Prompt History",
            "Habits",
        ]:
            button = QPushButton(name)
            button.setObjectName("NavButton")
            side.addWidget(button)
            self.buttons.append(button)

        side.addStretch()

        privacy = QLabel(
            "● LOCAL ONLY\n\n"
            "Prompts stored in\n"
            f"{APP_DIR}"
        )
        privacy.setObjectName("Privacy")
        privacy.setWordWrap(True)
        side.addWidget(privacy)

        # IMPORTANT: add the widget, not its layout
        root.addWidget(sidebar)
        

        self.stack = QStackedWidget()

        self.dashboard = Dashboard(self)
        self.inspector = Inspector(self)
        self.history = History(self)
        self.habits = Habits(self)

        self.stack.addWidget(self.dashboard)
        self.stack.addWidget(self.inspector)
        self.stack.addWidget(self.history)
        self.stack.addWidget(self.habits)

        root.addWidget(self.stack)

        for i, button in enumerate(self.buttons):
            button.clicked.connect(lambda checked=False, idx=i: self.navigate(idx))

    def navigate(self, index):
        self.stack.setCurrentIndex(index)

        if index == 0:
            self.dashboard.refresh()
        elif index == 2:
            self.history.refresh()
        elif index == 3:
            self.habits.refresh()


# ---------------- Main ----------------

if __name__ == "__main__":
    init_db()

    app = QApplication(sys.argv)

    app.setStyleSheet("""
        QWidget {
            font-family: Segoe UI, Arial, sans-serif;
            font-size: 14px;
        }

        QMainWindow {
            background: #f5f6f8;
        }

        #Sidebar {
            background: #15171c;
        }

        #Logo {
            color: white;
            font-size: 22px;
            font-weight: 700;
            padding: 20px 10px;
        }

        #NavButton {
            text-align: left;
            padding: 13px 14px;
            border: none;
            border-radius: 7px;
            color: #d5d7dc;
            background: transparent;
        }

        #NavButton:hover {
            background: #272a31;
            color: white;
        }

        #Privacy {
            color: #8f949e;
            font-size: 11px;
            padding: 10px;
        }

        #PageTitle {
            font-size: 28px;
            font-weight: 700;
            padding: 10px 0 15px 0;
        }

        #Card {
            background: white;
            border: 1px solid #e2e4e8;
            border-radius: 10px;
            padding: 10px;
        }

        #CardTitle {
            color: #777b84;
            font-size: 11px;
            font-weight: 700;
        }

        #CardValue {
            font-size: 28px;
            font-weight: 700;
        }

        #CardSubtitle {
            color: #858993;
            font-size: 11px;
        }

        QTextEdit {
            background: white;
            border: 1px solid #dfe2e7;
            border-radius: 8px;
            padding: 10px;
        }

        QPushButton {
            background: #20232a;
            color: white;
            border-radius: 7px;
            padding: 10px 16px;
        }

        QPushButton:hover {
            background: #30343d;
        }

        QListWidget {
            background: white;
            border: 1px solid #dfe2e7;
            border-radius: 8px;
        }
    """)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
