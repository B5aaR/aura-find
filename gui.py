import sys
import os
import json
import subprocess
import shutil
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QScrollArea, QLabel, QFrame,
    QGraphicsDropShadowEffect, QDialog, QTextEdit, QSizePolicy, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QByteArray, QTimer
from PyQt6.QtGui import QColor, QPainter, QBrush, QPixmap, QFont


# ══════════════════════════════════════════════════════
#  LOGO HELPERS
# ══════════════════════════════════════════════════════

def fetch_logo(pkg_name: str, size: int = 48) -> "QPixmap | None":
    base = pkg_name.lower().split("-")[0].split("_")[0]
    for domain in [f"{base}.org", f"{base}.com"]:
        try:
            r = requests.get(
                f"https://icons.duckduckgo.com/ip3/{domain}.ico",
                timeout=1.5
            )
            if r.status_code == 200 and len(r.content) > 200:
                px = QPixmap()
                px.loadFromData(QByteArray(r.content))
                if not px.isNull() and px.width() > 8:
                    return px.scaled(size, size,
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        except Exception:
            pass
    return None


def rounded_pixmap(src: QPixmap, size: int, radius: int) -> QPixmap:
    scaled = src.scaled(size, size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    p = QPainter(result)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(scaled))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, radius, radius)
    p.end()
    return result


def placeholder_pixmap(letter: str, color: str, size: int = 48) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, 12, 12)
    p.setPen(QColor("#0A0B18"))
    f = QFont("JetBrains Mono", size // 3)
    f.setBold(True)
    p.setFont(f)
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, letter.upper()[:1])
    p.end()
    return px


# ══════════════════════════════════════════════════════
#  OFFLINE SEARCH
# ══════════════════════════════════════════════════════

def search_offline(query: str) -> list:
    script_dir = os.path.dirname(os.path.realpath(__file__))
    json_path = os.path.join(script_dir, "data", "real_db.json")
    if not os.path.exists(json_path):
        return []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            db = json.load(f)
    except Exception:
        return []
    q = query.lower()
    results = []
    for app in db.get("apps", []):
        if (q in app.get("name", "").lower() or
                q in app.get("desc", "").lower() or
                q in app.get("category", "").lower()):
            results.append({
                "name":   app.get("name", ""),
                "repo":   app.get("category", "Wiki"),
                "desc":   app.get("desc", "No description."),
                "source": "offline",
            })
    return results[:12]


# ══════════════════════════════════════════════════════
#  WORKER 1 — Search (carries search_id to detect stale results)
# ══════════════════════════════════════════════════════

class SearchWorker(QThread):
    # Emits (search_id, results) so the UI can discard old ones
    results_ready = pyqtSignal(int, list)

    def __init__(self, query: str, search_id: int):
        super().__init__()
        self.query = query
        self.search_id = search_id

    def run(self):
        results = []

        try:
            r = requests.get(
                f"https://archlinux.org/packages/search/json/?q={self.query}",
                timeout=5)
            if r.status_code == 200:
                for pkg in r.json().get("results", [])[:10]:
                    results.append({
                        "name":   pkg.get("pkgname", ""),
                        "repo":   pkg.get("repo", "official"),
                        "desc":   pkg.get("pkgdesc", "No description."),
                        "source": "online",
                    })
        except Exception:
            pass

        try:
            r = requests.get(
                f"https://aur.archlinux.org/rpc/?v=5&type=search&arg={self.query}",
                timeout=5)
            if r.status_code == 200:
                for pkg in r.json().get("results", [])[:10]:
                    results.append({
                        "name":   pkg.get("Name", ""),
                        "repo":   "AUR",
                        "desc":   pkg.get("Description", "No description."),
                        "source": "online",
                    })
        except Exception:
            pass

        online_names = {r["name"].lower() for r in results}
        for pkg in search_offline(self.query):
            if pkg["name"].lower() not in online_names:
                results.append(pkg)

        self.results_ready.emit(self.search_id, results)


# ══════════════════════════════════════════════════════
#  WORKER 2 — Logo loader (parallel, per-card signals, also carries search_id)
# ══════════════════════════════════════════════════════

class LogoWorker(QThread):
    logo_ready = pyqtSignal(int, str, QPixmap)   # (search_id, pkg_name, pixmap)

    def __init__(self, names: list, search_id: int):
        super().__init__()
        self.names = names
        self.search_id = search_id
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(fetch_logo, n): n for n in self.names}
            for future in as_completed(futures):
                if self._stop:
                    break
                name = futures[future]
                try:
                    px = future.result()
                    if px and not px.isNull():
                        self.logo_ready.emit(self.search_id, name, px)
                except Exception:
                    pass


# ══════════════════════════════════════════════════════
#  HELPERS — check if a package is installed locally
# ══════════════════════════════════════════════════════

def is_installed(pkg_name: str) -> bool:
    """Returns True if pacman knows about this package being installed."""
    try:
        result = subprocess.run(
            ["pacman", "-Q", pkg_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return result.returncode == 0
    except Exception:
        return False


# ══════════════════════════════════════════════════════
#  WORKER 3 — Install OR Uninstall (runs pacman/yay, streams output)
# ══════════════════════════════════════════════════════

# Global password store — set once at startup, used for all sudo calls
_SUDO_PASSWORD: str = ""

def set_sudo_password(pw: str):
    global _SUDO_PASSWORD
    _SUDO_PASSWORD = pw

def run_sudo(cmd: list, output_cb) -> bool:
    """Run a command with sudo -S, feeding the cached password via stdin."""
    full_cmd = ["sudo", "-S", "-k"] + cmd
    output_cb(f"▶  Running:  sudo {' '.join(cmd)}\n")
    try:
        proc = subprocess.Popen(
            full_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        # Feed password once on first line (sudo -S reads from stdin)
        proc.stdin.write(_SUDO_PASSWORD + "\n")
        proc.stdin.flush()
        proc.stdin.close()
        for line in proc.stdout:
            stripped = line.rstrip()
            # Hide the "password:" prompt line sudo echoes back
            if stripped.lower().startswith("[sudo]") or stripped.endswith("password:"):
                continue
            output_cb(stripped)
        proc.wait()
        return proc.returncode == 0
    except Exception as e:
        output_cb(f"❌  Error: {e}")
        return False


class PkgWorker(QThread):
    output_line = pyqtSignal(str)
    finished_ok = pyqtSignal(bool)

    def __init__(self, pkg_name: str, is_aur: bool, uninstall: bool = False):
        super().__init__()
        self.pkg_name  = pkg_name
        self.is_aur    = is_aur
        self.uninstall = uninstall

    def run(self):
        if self.uninstall:
            if not shutil.which("pacman"):
                self.output_line.emit("❌  pacman not found. Are you on Arch Linux?")
                self.finished_ok.emit(False)
                return
            success = run_sudo(
                ["pacman", "-Rns", "--noconfirm", self.pkg_name],
                self.output_line.emit
            )
            self.output_line.emit(
                "\n✅  Uninstalled successfully!" if success else "\n❌  Uninstall failed"
            )
            self.finished_ok.emit(success)
        else:
            if self.is_aur:
                installer = shutil.which("yay") or shutil.which("paru")
                if not installer:
                    self.output_line.emit("❌  No AUR helper found (yay or paru).")
                    self.finished_ok.emit(False)
                    return
                # AUR helpers handle their own privilege escalation via sudo internally
                self.output_line.emit(f"▶  Running:  {installer} -S --noconfirm {self.pkg_name}\n")
                try:
                    proc = subprocess.Popen(
                        [installer, "-S", "--noconfirm", self.pkg_name],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        env={**os.environ, "SUDO_ASKPASS": "/bin/true"}
                    )
                    proc.stdin.write(_SUDO_PASSWORD + "\n")
                    proc.stdin.flush()
                    proc.stdin.close()
                    for line in proc.stdout:
                        stripped = line.rstrip()
                        if stripped.lower().startswith("[sudo]") or stripped.endswith("password:"):
                            continue
                        self.output_line.emit(stripped)
                    proc.wait()
                    success = proc.returncode == 0
                except Exception as e:
                    self.output_line.emit(f"❌  Error: {e}")
                    success = False
            else:
                if not shutil.which("pacman"):
                    self.output_line.emit("❌  pacman not found.")
                    self.finished_ok.emit(False)
                    return
                success = run_sudo(
                    ["pacman", "-S", "--noconfirm", self.pkg_name],
                    self.output_line.emit
                )
            self.output_line.emit(
                "\n✅  Installation complete!" if success else "\n❌  Installation failed"
            )
            self.finished_ok.emit(success)


# ══════════════════════════════════════════════════════
#  PKG DIALOG — live terminal for install OR uninstall
# ══════════════════════════════════════════════════════

class PkgDialog(QDialog):
    def __init__(self, pkg_name: str, is_aur: bool, uninstall: bool = False, parent=None):
        super().__init__(parent)
        self.uninstall = uninstall
        action_word = "Uninstalling" if uninstall else "Installing"
        self.setWindowTitle(f"{action_word}  {pkg_name}")
        self.resize(680, 420)
        self.setModal(False)

        # Red tint for uninstall, default for install
        terminal_color = "#F4A261" if uninstall else "#7BF1A8"
        title_icon     = "🗑" if uninstall else "⬇"

        self.setStyleSheet("""
            QDialog { background:#0A0B18; border:1px solid #1E2040; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        # Title row with icon
        title_row = QHBoxLayout()
        title_lbl = QLabel(
            f"{title_icon}  {action_word}  "
            f"<b style='color:{terminal_color}'>{pkg_name}</b>"
        )
        title_lbl.setStyleSheet(
            "font-size:15px; color:#DDE2FF; font-family:'JetBrains Mono',monospace;"
        )
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        layout.addLayout(title_row)

        # Terminal box
        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setStyleSheet(f"""
            QTextEdit {{
                background:#060710;
                color:{terminal_color};
                font-family:'JetBrains Mono','Fira Code',monospace;
                font-size:12px;
                border:1px solid #1A1E40;
                border-radius:8px;
                padding:10px;
            }}
        """)
        layout.addWidget(self.terminal)

        # Bottom row
        bottom = QHBoxLayout()
        waiting_text = "Uninstalling…" if uninstall else "Installing…"
        self.status_lbl = QLabel(waiting_text)
        self.status_lbl.setStyleSheet(
            "color:#445577; font-size:11px; font-family:'JetBrains Mono',monospace;"
        )
        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFixedHeight(32)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background:#1A1E40; color:#445577;
                border:1px solid #2A2E50; border-radius:8px;
                padding:0 20px; font-size:12px;
            }
            QPushButton:enabled {
                background:#4CC9F0; color:#0A0B18;
                border:none; font-weight:bold;
            }
            QPushButton:enabled:hover { background:#5DD8FA; }
        """)
        self.close_btn.clicked.connect(self.accept)
        bottom.addWidget(self.status_lbl)
        bottom.addStretch()
        bottom.addWidget(self.close_btn)
        layout.addLayout(bottom)

        # Start worker
        self.worker = PkgWorker(pkg_name, is_aur, uninstall)
        self.worker.output_line.connect(self._append)
        self.worker.finished_ok.connect(self._done)
        self.worker.start()

    def _append(self, line: str):
        self.terminal.append(line)
        sb = self.terminal.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _done(self, success: bool):
        self.status_lbl.setText("Done ✓" if success else "Failed ✗")
        self.status_lbl.setStyleSheet(
            f"color:{'#44CC88' if success else '#CC4444'};"
            "font-size:11px; font-family:'JetBrains Mono',monospace;"
        )
        self.close_btn.setEnabled(True)


# ══════════════════════════════════════════════════════
#  REPO COLOURS
# ══════════════════════════════════════════════════════

REPO_PALETTE = {
    "aur":       "#F4A261",
    "core":      "#4CC9F0",
    "extra":     "#7BF1A8",
    "community": "#C77DFF",
    "multilib":  "#F72585",
    "testing":   "#FFD166",
    "official":  "#4CC9F0",
}

def repo_color(repo: str) -> str:
    return REPO_PALETTE.get(repo.lower(), "#8899CC")


# ══════════════════════════════════════════════════════
#  APP CARD
# ══════════════════════════════════════════════════════

class AppCard(QFrame):
    def __init__(self, name: str, repo: str, desc: str,
                 source: str = "online", parent_window=None):
        super().__init__()
        self.pkg_name = name
        self.repo = repo
        self.parent_window = parent_window
        self.setObjectName("AppCard")
        accent = repo_color(repo)

        # Check installed state upfront (fast pacman -Q call)
        self._installed = is_installed(name)

        self.setStyleSheet(f"""
            QFrame#AppCard {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #111228, stop:1 #161730);
                border-radius: 16px;
                border: 1px solid #1E2040;
            }}
            QFrame#AppCard:hover {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #171A38, stop:1 #1C1E38);
                border: 1px solid {accent}60;
            }}
        """)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 100))
        self.setGraphicsEffect(shadow)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 18, 12)
        root.setSpacing(14)

        # Colour strip
        strip = QFrame()
        strip.setFixedWidth(3)
        strip.setFixedHeight(52)
        strip.setStyleSheet(f"""
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {accent}, stop:1 {accent}33);
            border-radius:2px;
        """)
        root.addWidget(strip, 0, Qt.AlignmentFlag.AlignVCenter)

        # Icon — placeholder shown immediately
        self.icon_lbl = QLabel()
        self.icon_lbl.setFixedSize(48, 48)
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_lbl.setStyleSheet("background:transparent;")
        self.icon_lbl.setPixmap(placeholder_pixmap(name, accent, 48))
        root.addWidget(self.icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        # Text column
        col = QVBoxLayout()
        col.setSpacing(4)
        col.setContentsMargins(0, 0, 0, 0)

        # Title + badges
        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("""
            font-family:'JetBrains Mono','Fira Code',monospace;
            font-size:15px; font-weight:bold; color:#DDE2FF;
        """)

        repo_badge = QLabel(f" {repo.upper()} ")
        repo_badge.setFixedHeight(20)
        repo_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        repo_badge.setStyleSheet(f"""
            background:{accent}20; color:{accent};
            border:1px solid {accent}50; border-radius:10px;
            padding:0 8px; font-size:10px; font-weight:bold;
            font-family:'JetBrains Mono',monospace;
        """)

        if source == "online":
            src_badge = QLabel(" 🌐 LIVE ")
            src_badge.setStyleSheet(
                "background:#0D2A20; color:#44CC88; border:1px solid #33AA6644;"
                "border-radius:10px; padding:0 6px; font-size:10px;"
                "font-family:'JetBrains Mono',monospace;"
            )
        else:
            src_badge = QLabel(" 📖 WIKI ")
            src_badge.setStyleSheet(
                "background:#2A2050; color:#8877CC; border:1px solid #4433AA44;"
                "border-radius:10px; padding:0 6px; font-size:10px;"
                "font-family:'JetBrains Mono',monospace;"
            )
        src_badge.setFixedHeight(20)

        title_row.addWidget(name_lbl)
        title_row.addWidget(repo_badge)
        title_row.addWidget(src_badge)
        title_row.addStretch()

        # Description
        desc_lbl = QLabel(desc[:150] + ("…" if len(desc) > 150 else ""))
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(
            "font-size:12px; color:#4A5A80;"
            "font-family:'Segoe UI','Ubuntu',sans-serif;"
        )

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        # Copy command button
        cmd = f"yay -S {name}" if repo.upper() == "AUR" else f"sudo pacman -S {name}"
        self._cmd = cmd
        self.copy_btn = QPushButton(f"  $ {cmd}")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setFixedHeight(28)
        self.copy_btn.setStyleSheet(f"""
            QPushButton {{
                background:#0E0F22; color:{accent};
                font-size:10px; font-family:'JetBrains Mono',monospace;
                border-radius:7px; padding:0 12px;
                border:1px solid {accent}30; text-align:left;
            }}
            QPushButton:hover {{ background:{accent}18; border-color:{accent}70; }}
        """)
        self.copy_btn.clicked.connect(self._copy)

        # Install / Uninstall button — styled differently based on state
        self.action_btn = QPushButton()
        self.action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_btn.setFixedHeight(28)
        self._accent = accent
        self._update_action_btn()
        self.action_btn.clicked.connect(self._on_action)

        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.action_btn)

        col.addLayout(title_row)
        col.addWidget(desc_lbl)
        col.addLayout(btn_row)
        root.addLayout(col)

    def _update_action_btn(self):
        """Redraw the button label and style based on current installed state."""
        accent = self._accent
        if self._installed:
            self.action_btn.setText("🗑  Uninstall")
            self.action_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: #CC4444;
                    font-weight: bold; font-size: 11px;
                    font-family: 'JetBrains Mono', monospace;
                    border-radius: 7px; padding: 0 14px;
                    border: 1px solid #CC444466;
                }}
                QPushButton:hover {{
                    background: #CC444422;
                    border-color: #CC4444;
                }}
                QPushButton:pressed {{ background: #CC444444; }}
                QPushButton:disabled {{
                    background: #2A2E50; color: #445577; border: none;
                }}
            """)
        else:
            self.action_btn.setText("⬇  Install")
            self.action_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {accent}; color: #0A0B18;
                    font-weight: bold; font-size: 11px;
                    font-family: 'JetBrains Mono', monospace;
                    border-radius: 7px; padding: 0 14px; border: none;
                }}
                QPushButton:hover {{ background: #FFFFFF; color: #0A0B18; }}
                QPushButton:pressed {{ background: {accent}BB; }}
                QPushButton:disabled {{
                    background: #2A2E50; color: #445577; border: none;
                }}
            """)

    def _copy(self):
        QApplication.clipboard().setText(self._cmd)
        self.copy_btn.setText("  ✓ Copied!")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText(f"  $ {self._cmd}"))

    def _on_action(self):
        if self._installed:
            self._uninstall()
        else:
            self._install()

    def _install(self):
        is_aur = self.repo.upper() == "AUR"
        dlg = PkgDialog(self.pkg_name, is_aur, uninstall=False, parent=self.parent_window)
        self.action_btn.setEnabled(False)
        self.action_btn.setText("Installing…")
        dlg.worker.finished_ok.connect(self._install_done)
        dlg.show()

    def _install_done(self, success: bool):
        if success:
            self._installed = True
        self.action_btn.setEnabled(True)
        self._update_action_btn()

    def _uninstall(self):
        is_aur = self.repo.upper() == "AUR"
        dlg = PkgDialog(self.pkg_name, is_aur, uninstall=True, parent=self.parent_window)
        self.action_btn.setEnabled(False)
        self.action_btn.setText("Uninstalling…")
        dlg.worker.finished_ok.connect(self._uninstall_done)
        dlg.show()

    def _uninstall_done(self, success: bool):
        if success:
            self._installed = False
        self.action_btn.setEnabled(True)
        self._update_action_btn()

    def set_logo(self, px: QPixmap):
        self.icon_lbl.setPixmap(rounded_pixmap(px, 48, 12))


# ══════════════════════════════════════════════════════
#  SEARCH BUTTON
# ══════════════════════════════════════════════════════

class SearchButton(QPushButton):
    def __init__(self):
        super().__init__("  🔍  Search")
        self.setFixedHeight(50)
        self.setMinimumWidth(130)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._idle()

    def _idle(self):
        self.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #4361EE, stop:1 #4CC9F0);
                color:white; font-size:13px; font-weight:bold;
                font-family:'JetBrains Mono',monospace;
                border-radius:12px; border:none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #5572FF, stop:1 #5DD8FA);
            }
            QPushButton:pressed { background:#2D3FBB; }
        """)

    def _loading(self):
        self.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #4CC9F0, stop:1 #7BF1A8);
                color:#0A0B18; font-size:13px; font-weight:bold;
                font-family:'JetBrains Mono',monospace;
                border-radius:12px; border:none;
            }
        """)

    def set_loading(self, val: bool):
        if val:
            self._loading()
            self.setText("  ⏳  Searching…")
            self.setEnabled(False)
        else:
            self._idle()
            self.setText("  🔍  Search")
            self.setEnabled(True)


# ══════════════════════════════════════════════════════
#  MAIN WINDOW
# ══════════════════════════════════════════════════════

CHIPS = ["gimp", "kdenlive", "vlc", "libreoffice", "audacity", "inkscape", "obs"]


class AuraStore(QWidget):
    def __init__(self):
        super().__init__()
        self.search_worker = None
        self.logo_worker   = None
        self._cards: dict  = {}
        self._search_id    = 0   # increments every search — stale results get discarded

        self.setWindowTitle("Aura Find — Open Source Alternatives")
        self.resize(980, 740)
        self.setMinimumSize(720, 540)

        self.setStyleSheet("""
            QWidget     { background-color:#0A0B18; color:#DDE2FF; }
            QScrollArea { border:none; background:transparent; }
            QScrollBar:vertical {
                background:#10112A; width:5px; border-radius:2px; margin:0;
            }
            QScrollBar::handle:vertical {
                background:#2A2D5A; border-radius:2px; min-height:24px;
            }
            QScrollBar::handle:vertical:hover { background:#4CC9F0; }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height:0; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 26, 36, 18)
        root.setSpacing(0)

        # ── HEADER ───────────────────────────────────────
        hdr = QHBoxLayout()
        brand = QLabel("◈  Aura Find")
        brand.setStyleSheet("""
            font-family:'JetBrains Mono',monospace;
            font-size:25px; font-weight:bold;
            color:#4CC9F0; letter-spacing:3px;
        """)
        tagline = QLabel("discover free & open-source alternatives")
        tagline.setAlignment(Qt.AlignmentFlag.AlignBottom)
        tagline.setStyleSheet(
            "font-size:12px; color:#2A3A5A; margin-left:10px;"
            "font-family:'Segoe UI','Ubuntu',sans-serif;"
        )

        script_dir = os.path.dirname(os.path.realpath(__file__))
        db_ok = os.path.exists(os.path.join(script_dir, "data", "real_db.json"))
        db_pill = QLabel("  📖 Offline DB ✓  " if db_ok else "  📖 Offline DB ✗  ")
        db_pill.setStyleSheet(
            f"font-size:11px; font-family:'JetBrains Mono',monospace;"
            f"color:{'#44CC88' if db_ok else '#CC4444'};"
            f"background:{'#0D2A20' if db_ok else '#2A0D0D'};"
            f"border:1px solid {'#33AA6633' if db_ok else '#AA333333'};"
            f"border-radius:8px; padding:4px 10px;"
        )

        hdr.addWidget(brand)
        hdr.addWidget(tagline, 0, Qt.AlignmentFlag.AlignBottom)
        hdr.addStretch()
        hdr.addWidget(db_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(hdr)
        root.addSpacing(18)

        # ── SEARCH BAR ───────────────────────────────────
        search_frame = QFrame()
        search_frame.setObjectName("SF")
        search_frame.setFixedHeight(56)
        search_frame.setStyleSheet("""
            QFrame#SF {
                background:#10112A; border-radius:14px;
                border:1px solid #1E2040;
            }
        """)
        sf = QHBoxLayout(search_frame)
        sf.setContentsMargins(18, 0, 8, 0)
        sf.setSpacing(10)

        lbl_icon = QLabel("⌕")
        lbl_icon.setStyleSheet("font-size:20px; color:#2A3A5A;")
        sf.addWidget(lbl_icon)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Search any app…  e.g. photoshop, spotify, premiere, discord"
        )
        self.search_input.setStyleSheet("""
            QLineEdit {
                background:transparent; border:none;
                font-size:15px; font-family:'Segoe UI','Ubuntu',sans-serif;
                color:#DDE2FF; padding:0;
            }
        """)
        self.search_input.returnPressed.connect(self.perform_search)
        sf.addWidget(self.search_input)

        self.search_btn = SearchButton()
        self.search_btn.clicked.connect(self.perform_search)
        sf.addWidget(self.search_btn)

        root.addWidget(search_frame)
        root.addSpacing(10)

        # ── QUICK CHIPS ──────────────────────────────────
        chips_row = QHBoxLayout()
        chips_row.setSpacing(6)
        try_lbl = QLabel("Try:")
        try_lbl.setStyleSheet(
            "color:#2A3A5A; font-size:11px; font-family:'JetBrains Mono',monospace;"
        )
        chips_row.addWidget(try_lbl)
        for tag in CHIPS:
            b = QPushButton(tag)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(24)
            b.setStyleSheet("""
                QPushButton {
                    background:#10112A; color:#3A4A7A;
                    border:1px solid #1A1E40; border-radius:12px;
                    padding:0 11px; font-size:11px;
                    font-family:'JetBrains Mono',monospace;
                }
                QPushButton:hover {
                    color:#4CC9F0; border-color:#4CC9F044; background:#14163A;
                }
            """)
            b.clicked.connect(lambda _, t=tag: self._chip(t))
            chips_row.addWidget(b)
        chips_row.addStretch()
        root.addLayout(chips_row)
        root.addSpacing(10)

        # ── STATUS ───────────────────────────────────────
        self.status_lbl = QLabel(
            "Search Arch repos, AUR & offline Arch Wiki simultaneously."
        )
        self.status_lbl.setStyleSheet(
            "color:#1E2A4A; font-size:11px; font-family:'JetBrains Mono',monospace;"
        )
        root.addWidget(self.status_lbl)
        root.addSpacing(8)

        # ── SCROLL AREA ──────────────────────────────────
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.results_widget = QWidget()
        self.results_widget.setStyleSheet("background:transparent;")
        self.results_layout = QVBoxLayout(self.results_widget)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.results_layout.setSpacing(10)
        self.results_layout.setContentsMargins(0, 0, 6, 0)
        self.scroll.setWidget(self.results_widget)
        root.addWidget(self.scroll)

        # ── FOOTER ───────────────────────────────────────
        root.addSpacing(4)
        footer = QLabel("Powered by Arch Linux · AUR · Arch Wiki Offline  •  Aura Find")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet(
            "color:#141828; font-size:10px; font-family:'JetBrains Mono',monospace;"
        )
        root.addWidget(footer)

    # ── helpers ──────────────────────────────────────────

    def _chip(self, tag: str):
        self.search_input.setText(tag)
        self.perform_search()

    def _clear(self):
        self._cards.clear()
        for i in reversed(range(self.results_layout.count())):
            w = self.results_layout.itemAt(i).widget()
            if w:
                w.deleteLater()

    def _stop_logo_worker(self):
        if self.logo_worker and self.logo_worker.isRunning():
            self.logo_worker.stop()
            self.logo_worker.wait(300)

    # ── search ───────────────────────────────────────────

    def perform_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        # Bump the ID — any in-flight worker with an old ID will be ignored
        self._search_id += 1
        current_id = self._search_id

        self._stop_logo_worker()
        self._clear()
        self.search_btn.set_loading(True)
        self.status_lbl.setText(f"Searching '{query}'…")

        self.search_worker = SearchWorker(query, current_id)
        self.search_worker.results_ready.connect(self._on_results)
        self.search_worker.start()

    def _on_results(self, search_id: int, results: list):
        # DISCARD if this belongs to an older search
        if search_id != self._search_id:
            return

        self._clear()

        if not results:
            msg = QLabel("  😕  No results found. Try a different keyword.")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setStyleSheet(
                "color:#2A3A5A; font-size:15px;"
                "font-family:'JetBrains Mono',monospace; padding:60px;"
            )
            self.results_layout.addWidget(msg)
            self.status_lbl.setText("No packages found.")
        else:
            for pkg in results:
                card = AppCard(
                    pkg["name"], pkg["repo"], pkg["desc"],
                    pkg.get("source", "online"),
                    parent_window=self
                )
                self.results_layout.addWidget(card)
                self._cards[pkg["name"].lower()] = card

            n = len(results)
            self.status_lbl.setText(
                f"Found {n} result{'s' if n != 1 else ''}  ·  "
                f"logos loading…  ·  click ⬇ Install to install"
            )
            self._start_logos([p["name"] for p in results], search_id)

        self.search_btn.set_loading(False)

    def _start_logos(self, names: list, search_id: int):
        self.logo_worker = LogoWorker(names, search_id)
        self.logo_worker.logo_ready.connect(self._on_logo)
        self.logo_worker.start()

    def _on_logo(self, search_id: int, name: str, px: QPixmap):
        # DISCARD logo if it's from a stale search
        if search_id != self._search_id:
            return
        card = self._cards.get(name.lower())
        if card:
            card.set_logo(px)


# ══════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════
#  STARTUP PASSWORD DIALOG
# ══════════════════════════════════════════════════════

class PasswordDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Aura Find — Authentication")
        self.setFixedSize(440, 260)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("QDialog { background:#0A0B18; border:1px solid #1E2040; border-radius:16px; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 24)
        layout.setSpacing(14)

        # Icon + title
        title = QLabel("🔐  Enter your password")
        title.setStyleSheet(
            "font-family:'JetBrains Mono',monospace; font-size:17px;"
            "font-weight:bold; color:#DDE2FF;"
        )
        layout.addWidget(title)

        subtitle = QLabel(
            "Aura Find needs your sudo password once to install\n"
            "and uninstall packages without asking again."
        )
        subtitle.setStyleSheet(
            "font-size:12px; color:#445577;"
            "font-family:'Segoe UI','Ubuntu',sans-serif;"
        )
        layout.addWidget(subtitle)

        # Password field
        self.pw_input = QLineEdit()
        self.pw_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_input.setPlaceholderText("sudo password…")
        self.pw_input.setFixedHeight(44)
        self.pw_input.setStyleSheet("""
            QLineEdit {
                background:#10112A; color:#DDE2FF;
                border:1px solid #2A2E50; border-radius:10px;
                font-size:14px; padding:0 14px;
                font-family:'Segoe UI','Ubuntu',sans-serif;
            }
            QLineEdit:focus { border-color:#4CC9F0; }
        """)
        self.pw_input.returnPressed.connect(self._try_auth)
        layout.addWidget(self.pw_input)

        # Error label (hidden until needed)
        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet(
            "color:#CC4444; font-size:11px; font-family:'JetBrains Mono',monospace;"
        )
        layout.addWidget(self.error_lbl)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        skip_btn = QPushButton("Skip (install won\'t work)")
        skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        skip_btn.setFixedHeight(36)
        skip_btn.setStyleSheet("""
            QPushButton {
                background:transparent; color:#334466;
                border:1px solid #1E2040; border-radius:9px;
                font-size:11px; padding:0 14px;
            }
            QPushButton:hover { color:#4CC9F0; border-color:#4CC9F033; }
        """)
        skip_btn.clicked.connect(self.reject)

        self.auth_btn = QPushButton("  Unlock  ")
        self.auth_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.auth_btn.setFixedHeight(36)
        self.auth_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #4361EE, stop:1 #4CC9F0);
                color:white; font-weight:bold; font-size:13px;
                font-family:'JetBrains Mono',monospace;
                border-radius:9px; border:none; padding:0 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #5572FF, stop:1 #5DD8FA);
            }
        """)
        self.auth_btn.clicked.connect(self._try_auth)

        btn_row.addWidget(skip_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.auth_btn)
        layout.addLayout(btn_row)

    def _try_auth(self):
        pw = self.pw_input.text()
        if not pw:
            self.error_lbl.setText("Please enter your password.")
            return

        self.auth_btn.setEnabled(False)
        self.auth_btn.setText("Checking…")
        QApplication.processEvents()

        # Validate: run `sudo -S true` with the given password
        try:
            proc = subprocess.run(
                ["sudo", "-S", "-k", "true"],
                input=pw + "\n",
                capture_output=True,
                text=True,
                timeout=8
            )
            if proc.returncode == 0:
                set_sudo_password(pw)
                self.accept()
            else:
                self.error_lbl.setText("❌  Wrong password. Try again.")
                self.pw_input.clear()
                self.pw_input.setFocus()
                self.auth_btn.setEnabled(True)
                self.auth_btn.setText("  Unlock  ")
        except subprocess.TimeoutExpired:
            self.error_lbl.setText("❌  Timed out. Try again.")
            self.auth_btn.setEnabled(True)
            self.auth_btn.setText("  Unlock  ")
        except FileNotFoundError:
            # sudo not found — not on Linux, skip silently
            set_sudo_password(pw)
            self.accept()


def start_sudo_keepalive():
    """Refresh sudo timestamp every 4 minutes so it never expires."""
    def refresh():
        try:
            subprocess.run(
                ["sudo", "-S", "-v"],
                input=_SUDO_PASSWORD + "\n",
                capture_output=True,
                text=True
            )
        except Exception:
            pass
    timer = QTimer()
    timer.setInterval(4 * 60 * 1000)   # 4 minutes
    timer.timeout.connect(refresh)
    timer.start()
    return timer   # keep reference alive


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Ask for password once at startup
    pw_dlg = PasswordDialog()
    pw_dlg.exec()   # blocks until accepted or skipped

    # Keep sudo alive in background if authenticated
    _keepalive_timer = None
    if _SUDO_PASSWORD:
        _keepalive_timer = start_sudo_keepalive()

    win = AuraStore()
    win.show()
    sys.exit(app.exec())
