"""Config package — project.json parsing, detection, and app state.

`ConfigBar` (unico simbolo Qt deste pacote) e resolvido SOB DEMANDA via PEP 562
(`__getattr__` de modulo). Motivo: modulos puros — `command_queue.provider_router`
e seu teste `test_module_is_pure_no_qt_import` — precisam ler as feature flags
(`workflow_app.config.feature_flags`) sem arrastar Qt transitivamente, e importar
qualquer submodulo executa este `__init__`. Import eager de `ConfigBar` aqui
quebraria a pureza do router. `from workflow_app.config import ConfigBar`
continua funcionando identico para os callers Qt.
"""

from typing import TYPE_CHECKING, Any

from workflow_app.config.app_state import AppState, app_state
from workflow_app.config.config_parser import PipelineConfig, detect_config, parse_config
from workflow_app.config.feature_flags import (
    delegation_flags_nonclaude_enabled,
    delegation_flags_nonclaude_flag_name,
    llm_config_v2_enabled,
    llm_config_v2_flag_name,
    llm_config_v2_state,
    llm_flags_rules_v2_enabled,
    llm_flags_rules_v2_flag_name,
    llm_flags_rules_v2_state,
)

if TYPE_CHECKING:
    from workflow_app.config.config_bar import ConfigBar


def __getattr__(name: str) -> Any:
    """Resolve `ConfigBar` sob demanda (mantem o pacote livre de Qt no import)."""
    if name == "ConfigBar":
        from workflow_app.config.config_bar import ConfigBar

        return ConfigBar
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Mantem `ConfigBar` visivel a introspecção apesar do import lazy.

    Sem isto, `dir(workflow_app.config)` deixaria de listar `ConfigBar` (PEP 562
    resolve por atributo, nao popula o `__dict__`), o que seria mudanca
    observavel de superficie para qualquer caller que introspecta o pacote.
    """
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "AppState",
    "app_state",
    "ConfigBar",
    "PipelineConfig",
    "delegation_flags_nonclaude_enabled",
    "delegation_flags_nonclaude_flag_name",
    "detect_config",
    "parse_config",
    "llm_config_v2_enabled",
    "llm_config_v2_flag_name",
    "llm_config_v2_state",
    "llm_flags_rules_v2_enabled",
    "llm_flags_rules_v2_flag_name",
    "llm_flags_rules_v2_state",
]
