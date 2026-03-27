"""
D19 Graphite Amber — Dark theme for Workflow App.

Palette:
  Background  #18181B  (zinc-900)
  Surface     #27272A  (zinc-800)
  Elevated    #3F3F46  (zinc-700)
  Border      #3F3F46
  Text        #FAFAFA
  TextMuted   #A1A1AA
  TextDisabled #71717A
  Primary     #FBBF24  (amber-400)
  PrimaryHov  #FDE68A
  Danger      #FB7185
  Success     #34D399
  Info        #38BDF8
"""

from __future__ import annotations

STYLESHEET = """
/* ─── Global ─────────────────────────────────────────────── */
* {
    font-family: "Inter", "Segoe UI", "Helvetica Neue", sans-serif;
    font-size: 13px;
    color: #FAFAFA;
}

QMainWindow, QDialog, QWidget {
    background-color: #18181B;
}

/* ─── Header / Surface ────────────────────────────────────── */
#HeaderBar, #MetricsBar {
    background-color: #27272A;
    border-bottom: 1px solid #3F3F46;
}

#ConfigBar {
    background-color: #27272A;
    border-bottom: 1px solid #3F3F46;
    min-height: 36px;
    max-height: 36px;
}

/* ─── Splitter ────────────────────────────────────────────── */
QSplitter::handle {
    background-color: #3F3F46;
}
QSplitter::handle:hover {
    background-color: #FBBF24;
}

/* ─── Sidebar / CommandQueue ──────────────────────────────── */
#CommandQueueWidget {
    background-color: #18181B;
    border-left: 1px solid #3F3F46;
    min-width: 200px;
}

#CommandQueueHeader {
    background-color: #27272A;
    border-bottom: 1px solid #3F3F46;
    padding: 8px 12px;
    font-size: 12px;
    font-weight: 600;
    color: #A1A1AA;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* ─── Output Panel ────────────────────────────────────────── */
#OutputPanel {
    background-color: #18181B;
}

QTextEdit#TerminalOutput {
    background-color: #0D1117;
    color: #E6EDF3;
    font-family: "JetBrains Mono", "Consolas", "Courier New", monospace;
    font-size: 13px;
    border: none;
    selection-background-color: #264F78;
}

#TerminalCanvas {
    background-color: #0D1117;
    border: none;
}

/* ─── Command Items ───────────────────────────────────────── */
#CommandItemWidget {
    background-color: #27272A;
    border-bottom: 1px solid #3F3F46;
    padding: 6px 10px;
}

#CommandItemWidget:hover {
    background-color: #3F3F46;
}

#CommandItemWidget[executing="true"] {
    border-left: 2px solid #38BDF8;
}

/* ─── Buttons ─────────────────────────────────────────────── */
QPushButton {
    background-color: #3F3F46;
    color: #FAFAFA;
    border: 1px solid #52525B;
    border-radius: 4px;
    padding: 6px 14px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #52525B;
    border-color: #71717A;
}

QPushButton:pressed {
    background-color: #27272A;
}

QPushButton:disabled {
    color: #52525B;
    border-color: #3F3F46;
}

QPushButton#PrimaryButton {
    background-color: #FBBF24;
    color: #18181B;
    border: none;
    font-weight: 700;
}

QPushButton#PrimaryButton:hover {
    background-color: #FDE68A;
}

QPushButton#PrimaryButton:pressed {
    background-color: #F59E0B;
}

QPushButton#PrimaryButton:disabled {
    background-color: #78350F;
    color: #92400E;
}

QPushButton#DangerButton {
    background-color: transparent;
    color: #FB7185;
    border: 1px solid #FB7185;
}

QPushButton#DangerButton:hover {
    background-color: #4C0519;
}

QPushButton#IconButton {
    background-color: transparent;
    border: none;
    padding: 4px;
    border-radius: 4px;
}

QPushButton#IconButton:hover {
    background-color: #3F3F46;
}

/* ─── Inputs ──────────────────────────────────────────────── */
QLineEdit, QComboBox, QTextEdit {
    background-color: #27272A;
    color: #FAFAFA;
    border: 1px solid #3F3F46;
    border-radius: 4px;
    padding: 6px 10px;
    selection-background-color: #3F3F46;
}

QLineEdit:focus, QTextEdit:focus {
    border-color: #FBBF24;
    outline: none;
}

QLineEdit#InteractiveInput:focus {
    border: 1px solid #FBBF24;
    height: 32px;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #27272A;
    border: 1px solid #3F3F46;
    selection-background-color: #3F3F46;
}

/* ─── Progress bar ────────────────────────────────────────── */
QProgressBar {
    background-color: #3F3F46;
    border: none;
    border-radius: 3px;
    text-align: center;
    color: transparent;
    height: 6px;
}

QProgressBar::chunk {
    background-color: #FBBF24;
    border-radius: 3px;
}

/* ─── ScrollBars ──────────────────────────────────────────── */
QScrollBar:vertical {
    background-color: #18181B;
    width: 8px;
    border: none;
}

QScrollBar::handle:vertical {
    background-color: #3F3F46;
    border-radius: 4px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #52525B;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background-color: #18181B;
    height: 8px;
    border: none;
}

QScrollBar::handle:horizontal {
    background-color: #3F3F46;
    border-radius: 4px;
    min-width: 20px;
}

/* ─── Tooltips ────────────────────────────────────────────── */
QToolTip {
    background-color: #3F3F46;
    color: #FAFAFA;
    border: 1px solid #52525B;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}

/* ─── Dialogs ─────────────────────────────────────────────── */
QDialog {
    background-color: #18181B;
}

#DialogHeader {
    background-color: #27272A;
    border-bottom: 1px solid #3F3F46;
    min-height: 56px;
    max-height: 56px;
    padding: 0 16px;
}

#DialogFooter {
    background-color: #27272A;
    border-top: 1px solid #3F3F46;
    min-height: 56px;
    max-height: 56px;
    padding: 0 24px;
}

#DialogTitle {
    font-size: 16px;
    font-weight: 700;
    color: #FAFAFA;
}

/* ─── Review list (PipelineCreator page 2) ────────────────── */
#ReviewList {
    background-color: #18181B;
    border: 1px solid #3F3F46;
    border-radius: 8px;
}

/* ─── Choice cards (PipelineCreator page 0) ──────────────── */
#ChoiceCard {
    background-color: #27272A;
    border: 2px solid #3F3F46;
    border-radius: 12px;
    padding: 16px;
}

#ChoiceCard:hover {
    border-color: #FBBF24;
}

/* ─── Badges ──────────────────────────────────────────────── */
#BadgeOpus {
    background-color: #7C3AED;
    color: #FFFFFF;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 600;
}

#BadgeSonnet {
    background-color: #2563EB;
    color: #FFFFFF;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 600;
}

#BadgeHaiku {
    background-color: #059669;
    color: #FFFFFF;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 600;
}

#BadgeInteractive {
    background-color: #92400E;
    color: #FDE68A;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 11px;
}

#BadgeAuto {
    background-color: #1E3A5F;
    color: #93C5FD;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 11px;
}

/* ─── Notification / Toast ────────────────────────────────── */
#NotificationBanner {
    background-color: #27272A;
    border-left: 3px solid #FBBF24;
    border-radius: 4px;
    padding: 8px 12px;
}

#NotificationBanner[type="error"] {
    border-left-color: #FB7185;
}

#NotificationBanner[type="success"] {
    border-left-color: #34D399;
}

#NotificationBanner[type="warning"] {
    border-left-color: #F97316;
}

/* ─── Metrics bar specific ────────────────────────────────── */
#MetricsBarLabel {
    color: #A1A1AA;
    font-size: 12px;
}

#MetricsBarValue {
    color: #FAFAFA;
    font-size: 12px;
    font-weight: 600;
}

#MetricsBarCounter {
    color: #FBBF24;
    font-size: 12px;
    font-weight: 600;
}

/* ─── Config bar ──────────────────────────────────────────── */
#ProjectName {
    color: #FBBF24;
    font-size: 13px;
    font-weight: 700;
}

#ProjectHex {
    color: #71717A;
    font-size: 11px;
}

/* ─── History viewer ──────────────────────────────────────── */
#HistoryWidget {
    background-color: #18181B;
}

#FilterPanel {
    background-color: #27272A;
    border-right: 1px solid #3F3F46;
    min-width: 180px;
    max-width: 180px;
}
"""


def apply_theme(app) -> None:
    """Apply D19 Graphite Amber theme to the QApplication."""
    app.setStyleSheet(STYLESHEET)
