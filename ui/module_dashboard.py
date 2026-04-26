"""Per-module timeline + budget visualization dashboard."""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QProgressBar, QTableWidget, QTableWidgetItem,
                             QTabWidget, QScrollArea)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QColor
from pathlib import Path
import json
from typing import Dict, Optional

class ModuleDashboard(QWidget):
    """Per-module timeline + budget visualization."""

    status_changed = pyqtSignal(str, str)

    def __init__(self, module_id: int):
        super().__init__()
        self.module_id = module_id
        self.scratchpad_path = Path(f".claude/scratchpads/{module_id}")
        self.init_ui()

        # File watcher for real-time updates
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_dashboard)
        self.timer.start(1000)

    def init_ui(self):
        """Initialize UI layout."""
        layout = QVBoxLayout()

        # Header: Module info
        header = self.create_header()
        layout.addLayout(header)

        # Tabs for different views
        tabs = QTabWidget()
        tabs.addTab(self.create_phase_timeline(), "Timeline")
        tabs.addTab(self.create_budget_visualization(), "Budget")
        tabs.addTab(self.create_action_log(), "Logs")

        layout.addWidget(tabs)

        # Control buttons
        controls = self.create_controls()
        layout.addLayout(controls)

        self.setLayout(layout)
        self.setWindowTitle(f"Module {self.module_id} Dashboard")
        self.resize(1200, 800)

    def create_header(self) -> QHBoxLayout:
        """Create header with module info."""
        layout = QHBoxLayout()

        module_label = QLabel(f"Module {self.module_id}")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        module_label.setFont(font)

        slug_label = QLabel(self.get_module_slug())
        status_label = QLabel(self.get_module_status())

        layout.addWidget(module_label)
        layout.addWidget(slug_label)
        layout.addWidget(status_label)
        layout.addStretch()

        return layout

    def create_phase_timeline(self) -> QWidget:
        """Create vertical timeline A→I with progress bars."""
        phases = ["A", "B", "C", "D", "D.5", "E", "F", "F.2", "G", "H", "I"]
        layout = QVBoxLayout()

        self.phase_widgets = {}

        for phase in phases:
            phase_layout = QHBoxLayout()

            phase_label = QLabel(f"Phase {phase}")
            phase_label.setMinimumWidth(80)

            # Progress bar
            progress = QProgressBar()
            progress.setValue(self.get_phase_progress(phase))
            progress.setStyleSheet(self.get_phase_color(phase))

            # Token info
            tokens_label = QLabel(self.get_phase_tokens(phase))
            tokens_label.setMinimumWidth(150)

            phase_layout.addWidget(phase_label, 1)
            phase_layout.addWidget(progress, 3)
            phase_layout.addWidget(tokens_label, 2)

            layout.addLayout(phase_layout)
            self.phase_widgets[phase] = {
                "progress": progress,
                "tokens": tokens_label
            }

        container = QWidget()
        container.setLayout(layout)

        scroll = QScrollArea()
        scroll.setWidget(container)
        scroll.setWidgetResizable(True)

        return scroll

    def create_budget_visualization(self) -> QWidget:
        """Create budget summary visualization."""
        layout = QVBoxLayout()

        # Total budget summary
        summary = self.get_budget_summary()
        budget_text = f"Total: {summary['used']:,}/{summary['budget']:,} tokens ({summary['pct']}%)"
        summary_label = QLabel(budget_text)
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        summary_label.setFont(font)
        layout.addWidget(summary_label)

        # Progress bar for overall budget
        overall_progress = QProgressBar()
        overall_progress.setValue(summary['pct'])
        layout.addWidget(overall_progress)

        # Per-phase breakdown table
        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Phase", "Used", "Budget", "Utilization"])
        table.setRowCount(11)

        phases = ["A", "B", "C", "D", "D.5", "E", "F", "F.2", "G", "H", "I"]
        for idx, phase in enumerate(phases):
            tokens = self.get_phase_tokens_raw(phase)
            table.setItem(idx, 0, QTableWidgetItem(phase))
            table.setItem(idx, 1, QTableWidgetItem(f"{tokens['used']:,}"))
            table.setItem(idx, 2, QTableWidgetItem(f"{tokens['budget']:,}"))
            pct = int((tokens['used'] / tokens['budget'] * 100)) if tokens['budget'] > 0 else 0
            table.setItem(idx, 3, QTableWidgetItem(f"{pct}%"))

        table.resizeColumnsToContents()
        layout.addWidget(table)

        container = QWidget()
        container.setLayout(layout)
        return container

    def create_action_log(self) -> QWidget:
        """Create action/error log table."""
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Timestamp", "Severity", "Message"])

        error_log = self.scratchpad_path / "ERROR-LOG.jsonl"
        rows = 0

        if error_log.exists():
            lines = error_log.read_text().strip().split('\n')
            table.setRowCount(min(20, len(lines)))

            for idx, line in enumerate(reversed(lines[-20:])):
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    row = rows
                    table.setItem(row, 0, QTableWidgetItem(entry.get("timestamp", "")))
                    table.setItem(row, 1, QTableWidgetItem(entry.get("severity", "")))
                    table.setItem(row, 2, QTableWidgetItem(entry.get("message", "")))
                    rows += 1
                except json.JSONDecodeError:
                    pass

        table.resizeColumnsToContents()
        return table

    def create_controls(self) -> QHBoxLayout:
        """Create control buttons."""
        layout = QHBoxLayout()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.update_dashboard)

        export_btn = QPushButton("Export Report")
        export_btn.clicked.connect(self.export_report)

        layout.addWidget(refresh_btn)
        layout.addWidget(export_btn)
        layout.addStretch()

        return layout

    def get_phase_progress(self, phase: str) -> int:
        """Return 0-100 progress for phase."""
        state_file = self.scratchpad_path / "DELIVERY-STATE.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    state = json.load(f)
                    if phase in state.get("phase_status", {}):
                        phase_data = state["phase_status"][phase]
                        if phase_data.get("status") == "completed":
                            return 100
                        elif phase_data.get("status") == "in_progress":
                            return 50
            except json.JSONDecodeError:
                pass
        return 0

    def get_phase_color(self, phase: str) -> str:
        """Return QSS color based on completion."""
        progress = self.get_phase_progress(phase)
        if progress == 100:
            return "QProgressBar { background-color: #90EE90; }"
        elif progress == 50:
            return "QProgressBar { background-color: #FFE4B5; }"
        return "QProgressBar { background-color: #D3D3D3; }"

    def get_phase_tokens(self, phase: str) -> str:
        """Return token usage for phase."""
        tokens = self.get_phase_tokens_raw(phase)
        return f"{tokens['used']:,}/{tokens['budget']:,}"

    def get_phase_tokens_raw(self, phase: str) -> Dict:
        """Return raw token numbers for phase."""
        delivery_file = Path("delivery.json")
        default = {"used": 0, "budget": 0}

        if delivery_file.exists():
            try:
                with open(delivery_file) as f:
                    delivery = json.load(f)
                    budget_used = delivery.get("opus_47", {}).get("task_budget_used", {})
                    module_key = f"module_{self.module_id}"
                    if module_key in budget_used:
                        phase_key = f"phase_{phase}"
                        if phase_key in budget_used[module_key]:
                            return {
                                "used": budget_used[module_key][phase_key].get("tokens_used", 0),
                                "budget": budget_used[module_key][phase_key].get("budget", 0)
                            }
            except json.JSONDecodeError:
                pass

        return default

    def get_budget_summary(self) -> Dict:
        """Return total budget info."""
        delivery_file = Path("delivery.json")
        summary = {"used": 0, "budget": 0, "pct": 0}

        if delivery_file.exists():
            try:
                with open(delivery_file) as f:
                    delivery = json.load(f)
                    module_key = f"module_{self.module_id}"
                    budget_used = delivery.get("opus_47", {}).get("task_budget_used", {}).get(module_key, {})

                    summary["used"] = budget_used.get("total", {}).get("tokens_used", 0)
                    summary["budget"] = budget_used.get("total", {}).get("budget", 0)

                    if summary["budget"] > 0:
                        summary["pct"] = int((summary["used"] / summary["budget"]) * 100)
            except json.JSONDecodeError:
                pass

        return summary

    def get_module_slug(self) -> str:
        """Get module slug from scratchpad."""
        progress_file = self.scratchpad_path / "PHASE-PROGRESS.json"
        if progress_file.exists():
            try:
                with open(progress_file) as f:
                    progress = json.load(f)
                    return progress.get("module_slug", "unknown")
            except json.JSONDecodeError:
                pass
        return "unknown"

    def get_module_status(self) -> str:
        """Get module status."""
        state_file = self.scratchpad_path / "DELIVERY-STATE.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    state = json.load(f)
                    return f"Status: {state.get('status', 'unknown')}"
            except json.JSONDecodeError:
                pass
        return "Status: unknown"

    def update_dashboard(self):
        """Called by timer to update in real-time."""
        if hasattr(self, 'phase_widgets'):
            phases = ["A", "B", "C", "D", "D.5", "E", "F", "F.2", "G", "H", "I"]
            for phase in phases:
                if phase in self.phase_widgets:
                    self.phase_widgets[phase]["progress"].setValue(self.get_phase_progress(phase))
                    self.phase_widgets[phase]["progress"].setStyleSheet(self.get_phase_color(phase))
                    self.phase_widgets[phase]["tokens"].setText(self.get_phase_tokens(phase))

    def export_report(self):
        """Export dashboard data as JSON."""
        report = {
            "module_id": self.module_id,
            "module_slug": self.get_module_slug(),
            "status": self.get_module_status(),
            "budget_summary": self.get_budget_summary(),
            "phases": {}
        }

        phases = ["A", "B", "C", "D", "D.5", "E", "F", "F.2", "G", "H", "I"]
        for phase in phases:
            tokens = self.get_phase_tokens_raw(phase)
            report["phases"][phase] = {
                "progress": self.get_phase_progress(phase),
                "tokens_used": tokens["used"],
                "tokens_budget": tokens["budget"],
                "utilization_pct": int((tokens["used"] / tokens["budget"] * 100)) if tokens["budget"] > 0 else 0
            }

        export_file = self.scratchpad_path / "DASHBOARD-EXPORT.json"
        with open(export_file, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"✓ Report exported to {export_file}")

if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    module_id = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    dashboard = ModuleDashboard(module_id)
    dashboard.show()
    sys.exit(app.exec())
