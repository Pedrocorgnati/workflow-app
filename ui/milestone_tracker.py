"""Milestone tracking dashboard."""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
                             QLabel, QProgressBar, QHeaderView)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from pathlib import Path
import json
from datetime import datetime
from typing import List, Dict

class MilestoneTracker(QWidget):
    """Track milestone completion progress."""

    def __init__(self, module_id: int = 0):
        super().__init__()
        self.module_id = module_id
        self.milestones = self.load_milestones()
        self.init_ui()

        # Real-time updates
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(5000)

    def init_ui(self):
        layout = QVBoxLayout()

        # Header
        title = QLabel(f"Milestone Tracker - Module {self.module_id}")
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(self.calculate_progress())
        layout.addWidget(self.progress_bar)

        # Table: milestones
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "ID", "Phase", "Name", "Target Date", "Status", "Actual Date", "Owner"
        ])

        self.populate_table()
        layout.addWidget(self.table)
        self.setLayout(layout)

        self.setWindowTitle(f"Milestone Tracker - Module {self.module_id}")
        self.resize(1200, 600)

    def load_milestones(self) -> List[Dict]:
        """Load milestone file for module."""
        ms_file = Path(f".claude/milestones/module-{self.module_id}.json")
        if ms_file.exists():
            try:
                with open(ms_file) as f:
                    data = json.load(f)
                    return data.get("delivery_timeline", {}).get("milestones", [])
            except json.JSONDecodeError:
                pass
        return []

    def populate_table(self):
        """Populate table with milestone data."""
        self.table.setRowCount(len(self.milestones))

        for row, ms in enumerate(self.milestones):
            self.table.setItem(row, 0, QTableWidgetItem(ms.get("id", "")))
            self.table.setItem(row, 1, QTableWidgetItem(ms.get("phase", "")))
            self.table.setItem(row, 2, QTableWidgetItem(ms.get("name", "")))
            self.table.setItem(row, 3, QTableWidgetItem(ms.get("target_date", "")))

            status = "✓ Complete" if ms.get("completed") else "In Progress"
            self.table.setItem(row, 4, QTableWidgetItem(status))
            self.table.setItem(row, 5, QTableWidgetItem(ms.get("actual_completion_date", "")))
            self.table.setItem(row, 6, QTableWidgetItem(ms.get("owner", "")))

        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def calculate_progress(self) -> int:
        """Calculate overall progress percentage."""
        if not self.milestones:
            return 0

        completed = sum(1 for m in self.milestones if m.get("completed"))
        return int((completed / len(self.milestones)) * 100)

    def refresh(self):
        """Update from milestone file."""
        self.milestones = self.load_milestones()
        self.populate_table()
        self.progress_bar.setValue(self.calculate_progress())

if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    module_id = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    tracker = MilestoneTracker(module_id)
    tracker.show()
    sys.exit(app.exec())
