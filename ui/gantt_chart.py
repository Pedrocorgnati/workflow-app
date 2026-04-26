"""Gantt chart visualization for modules."""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QScrollArea
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from pathlib import Path
import json
from datetime import datetime

class GanttChart(QWidget):
    """Gantt chart visualization for modules."""

    def __init__(self):
        super().__init__()
        self.milestones = self.load_milestones()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        title = QLabel("Gantt Chart (Project Timeline)")
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        # ASCII timeline for MVP
        timeline_text = self.render_ascii_gantt()
        label = QLabel(timeline_text)
        label.setFont(QFont("Courier", 9))
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidget(label)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)

        self.setLayout(layout)
        self.setWindowTitle("Gantt Chart")
        self.resize(1000, 600)

    def load_milestones(self) -> list:
        """Load all milestone files."""
        milestones = []
        ms_dir = Path(".claude/milestones")
        if ms_dir.exists():
            for ms_file in sorted(ms_dir.glob("*.json")):
                try:
                    with open(ms_file) as f:
                        milestones.append(json.load(f))
                except json.JSONDecodeError:
                    pass
        return milestones

    def render_ascii_gantt(self) -> str:
        """ASCII Gantt chart."""
        if not self.milestones:
            return "No milestones found. Run /modules:build-milestones to generate."

        output = "Module Timeline:\n"
        output += "=" * 100 + "\n\n"

        for ms in self.milestones:
            module_id = ms.get("module_id", "?")
            slug = ms.get("module_slug", "unknown")
            timeline = ms.get("delivery_timeline", {})
            start = timeline.get("start_date", "?")
            end = timeline.get("end_date", "?")
            days = timeline.get("total_days", 0)

            output += f"Module {module_id:2d} | {slug:20s} | {start} → {end} | {days:2d}d\n"

            # Phase breakdown
            milestones_list = timeline.get("milestones", [])
            for mile in milestones_list[:3]:  # Show first 3
                phase = mile.get("phase", "?")
                name = mile.get("name", "")[:40]
                target = mile.get("target_date", "?")
                output += f"         ├─ {phase:4s} | {name:40s} | {target}\n"

            if len(milestones_list) > 3:
                output += f"         ├─ ... ({len(milestones_list) - 3} more milestones)\n"

            output += "\n"

        return output

    def export_to_png(self, filename: str):
        """Export chart to PNG."""
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            from datetime import datetime

            fig, ax = plt.subplots(figsize=(14, max(4, len(self.milestones) * 0.4)))

            for i, ms in enumerate(self.milestones):
                module_id = ms.get("module_id", i)
                timeline = ms.get("delivery_timeline", {})
                start_str = timeline.get("start_date", "2026-04-17")
                end_str = timeline.get("end_date", "2026-05-17")

                try:
                    start = datetime.fromisoformat(start_str)
                    end = datetime.fromisoformat(end_str)
                    duration = (end - start).days

                    ax.barh(i, duration, left=start, height=0.6, label=f"Module {module_id}")
                except (ValueError, TypeError):
                    pass

            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            ax.set_xlabel("Timeline")
            ax.set_ylabel("Modules")
            ax.set_title("Gantt Chart - Project Timeline")
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(filename, dpi=100)
            print(f"✓ Gantt chart exported to {filename}")
        except ImportError:
            print("⚠ matplotlib not installed. PNG export unavailable.")

if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    chart = GanttChart()
    chart.show()
    sys.exit(app.exec())
