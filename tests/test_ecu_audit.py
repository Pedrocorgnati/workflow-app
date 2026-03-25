"""ECU Audit — Zero Órfãos, Zero Silêncio, Zero Estados Indefinidos (module-16/TASK-3)."""
from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_main_window_has_setup_ui_method():
    """MainWindow deve ter _setup_ui definido como método."""
    from workflow_app.main_window import MainWindow

    assert callable(getattr(MainWindow, "_setup_ui", None))


def test_signal_bus_singleton():
    """signal_bus deve ser o mesmo objeto em imports diferentes."""
    from workflow_app import signal_bus as sb1
    from workflow_app.signal_bus import signal_bus as sb2

    assert sb1.signal_bus is sb2


def test_app_state_singleton():
    """app_state module-level singleton deve ser acessível de múltiplos pontos."""
    from workflow_app.config import app_state as as2
    from workflow_app.config.app_state import app_state as as1

    assert as1 is as2


def test_design_tokens_importable():
    """Tokens de design devem ser importáveis sem erro."""
    from workflow_app.tokens import COLORS, SPACING, TYPOGRAPHY

    assert COLORS.background == "#18181B"
    assert COLORS.primary == "#FBBF24"
    assert TYPOGRAPHY.font_ui == "Inter"
    assert SPACING.md == 12


def test_theme_file_exists():
    """theme.py deve existir e conter estilos."""
    theme_path = PROJECT_ROOT / "src" / "workflow_app" / "theme.py"
    assert theme_path.exists(), "theme.py não encontrado"


def test_command_status_enum_completeness():
    """CommandStatus deve ter exatamente 6 membros."""
    from workflow_app.domain import CommandStatus

    assert len(CommandStatus) == 6


def test_pipeline_status_enum_has_required_members():
    """PipelineStatus deve conter os membros essenciais do fluxo."""
    from workflow_app.domain import PipelineStatus

    values = {s.value for s in PipelineStatus}
    required = {"executando", "pausado", "concluido", "cancelado", "interrompido"}
    assert required.issubset(values)


def test_model_type_enum():
    """ModelType deve ter Opus, Sonnet, Haiku."""
    from workflow_app.domain import ModelType

    assert ModelType.OPUS.value == "opus"
    assert ModelType.SONNET.value == "sonnet"
    assert ModelType.HAIKU.value == "haiku"
