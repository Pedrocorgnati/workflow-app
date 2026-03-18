"""
NotificationService — Notificações desktop via QSystemTrayIcon (module-15/TASK-2).

Degradação silenciosa: se o sistema de bandeja não estiver disponível
(ex: servidor headless, tiling WMs sem suporte), todas as chamadas
são no-ops e um warning é logado.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QSystemTrayIcon

logger = logging.getLogger(__name__)

# Ícone placeholder 32x32 em SVG (amber 'W' sobre fundo escuro)
_APP_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="6" fill="#18181B"/>
  <text x="16" y="23" font-family="monospace" font-size="18" font-weight="bold"
        fill="#FBBF24" text-anchor="middle">W</text>
</svg>"""


def _make_app_icon() -> QIcon:
    """Cria ícone do app a partir do SVG."""
    try:
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QPainter
        from PySide6.QtSvg import QSvgRenderer

        renderer = QSvgRenderer(QByteArray(_APP_ICON_SVG.encode()))
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)
    except Exception:
        return QIcon()


class NotificationService(QObject):
    """Serviço de notificações desktop via QSystemTrayIcon.

    Degradação silenciosa: se o sistema de bandeja não estiver disponível
    (ex: servidor headless, tiling WMs sem suporte), todas as chamadas
    são no-ops e um warning é logado.

    Uso típico:
        service = NotificationService()
        ok = service.setup(parent_widget)
        if ok:
            service.notify_pipeline_done("meu-projeto", "02:30", errors=0)
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tray: QSystemTrayIcon | None = None
        self._available: bool = False
        self._icon = _make_app_icon()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup(self, parent=None) -> bool:
        """Inicializa o QSystemTrayIcon.

        Args:
            parent: widget pai (opcional).

        Returns:
            True se notificações estão disponíveis, False caso contrário.
        """
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                logger.warning(
                    "NotificationService: bandeja do sistema não disponível. "
                    "Notificações desabilitadas."
                )
                self._available = False
                return False

            self._tray = QSystemTrayIcon(self._icon, parent)
            self._tray.setToolTip("SystemForge Desktop")
            self._available = True
            logger.info("NotificationService: inicializado com sucesso.")
            return True

        except Exception as exc:
            logger.warning("NotificationService: falha no setup — %s", exc)
            self._available = False
            return False

    def show_tray_icon(self, executing: bool = False) -> None:
        """Exibe ou atualiza o ícone na bandeja."""
        if not self._available or self._tray is None:
            return
        tooltip = "SystemForge Desktop — Executando" if executing else "SystemForge Desktop"
        self._tray.setToolTip(tooltip)
        if not self._tray.isVisible():
            self._tray.show()

    def hide_tray_icon(self) -> None:
        """Remove o ícone da bandeja."""
        if self._tray is not None:
            self._tray.hide()

    # ------------------------------------------------------------------
    # Notificações
    # ------------------------------------------------------------------

    def notify_pipeline_done(
        self,
        project: str,
        duration: str,
        errors: int,
    ) -> None:
        """Notifica conclusão do pipeline.

        Args:
            project: nome do projeto.
            duration: string formatada da duração (ex: "02:30").
            errors: número de comandos com erro.
        """
        if not self._available or self._tray is None:
            return

        title = "Pipeline Concluído" if errors == 0 else "Pipeline Concluído com Erros"
        icon = (
            QSystemTrayIcon.MessageIcon.Information
            if errors == 0
            else QSystemTrayIcon.MessageIcon.Warning
        )
        message = f"{project} — {duration}"
        if errors > 0:
            message += f"\n{errors} comando(s) com erro"

        try:
            self._tray.showMessage(title, message, icon, msecs=4000)
        except Exception as exc:
            logger.warning("NotificationService.notify_pipeline_done: %s", exc)

    def notify_command_error(self, command: str, error: str) -> None:
        """Notifica falha de um comando específico.

        Args:
            command: nome do comando que falhou (ex: "/prd-create").
            error: mensagem de erro (truncada a 100 chars).
        """
        if not self._available or self._tray is None:
            return

        truncated = error[:100] + ("..." if len(error) > 100 else "")
        try:
            self._tray.showMessage(
                "Erro no Comando",
                f"{command}\n{truncated}",
                QSystemTrayIcon.MessageIcon.Critical,
                msecs=5000,
            )
        except Exception as exc:
            logger.warning("NotificationService.notify_command_error: %s", exc)

    def notify_pipeline_paused(self, command: str) -> None:
        """Notifica que o pipeline foi pausado aguardando interação.

        Args:
            command: nome do comando que aguarda interação.
        """
        if not self._available or self._tray is None:
            return

        try:
            self._tray.showMessage(
                "Pipeline Pausado",
                f"Aguardando interação em: {command}",
                QSystemTrayIcon.MessageIcon.Information,
                msecs=3000,
            )
        except Exception as exc:
            logger.warning("NotificationService.notify_pipeline_paused: %s", exc)

    @property
    def is_available(self) -> bool:
        return self._available
