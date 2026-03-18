"""
AppState — Estado global mutável da aplicação (módulo-03/TASK-2).

Mantém o PipelineConfig atualmente carregado. Acesso via singleton:
    from workflow_app.config.app_state import app_state

Não use diretamente em widgets — prefira signals do SignalBus
para reagir a mudanças de estado.
"""

from __future__ import annotations

from workflow_app.config.config_parser import PipelineConfig


class AppState:
    """Estado mutable global da aplicação (não é QObject).

    Mantém a referência ao PipelineConfig atualmente carregado.
    """

    def __init__(self) -> None:
        self._config: PipelineConfig | None = None

    @property
    def config(self) -> PipelineConfig | None:
        return self._config

    @property
    def has_config(self) -> bool:
        return self._config is not None

    def set_config(self, config: PipelineConfig) -> None:
        self._config = config

    def clear_config(self) -> None:
        self._config = None

    @property
    def project_name(self) -> str:
        if self._config:
            return self._config.project_name
        return ""


# Singleton
app_state = AppState()
