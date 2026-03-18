"""
Version checker for factory templates (module-05/TASK-4).

Detects when factory templates were generated with a different CLAUDE.md
version and signals that they may need refreshing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from workflow_app.templates.claude_md_hasher import compute_hash, find_claude_md
from workflow_app.templates.template_manager import TemplateManager

logger = logging.getLogger(__name__)


@dataclass
class VersionCheckResult:
    """Result of checking factory template versions against current CLAUDE.md."""

    is_outdated: bool = False
    current_hash: str | None = None
    outdated_names: list[str] = field(default_factory=list)


class VersionChecker:
    """Check if factory templates are aligned with the current CLAUDE.md.

    Usage:
        checker = VersionChecker(manager)
        result = checker.check_factory_templates()
        if result.is_outdated:
            # show banner or auto-refresh
    """

    def __init__(self, manager: TemplateManager) -> None:
        self._manager = manager
        self._suppressed: bool = False

    def check_factory_templates(
        self, claude_md_path: str | None = None,
    ) -> VersionCheckResult:
        """Check if any factory template has a divergent sha256.

        Args:
            claude_md_path: explicit path to CLAUDE.md. If None, uses
                           find_claude_md() to auto-detect.

        Returns:
            VersionCheckResult with outdated template names.
        """
        if self._suppressed:
            return VersionCheckResult()

        path = claude_md_path or find_claude_md()
        current_hash = compute_hash(path) if path else None

        if current_hash is None:
            logger.warning(
                "CLAUDE.md não encontrado. Versionamento de templates desabilitado."
            )
            return VersionCheckResult()

        templates = self._manager.list_templates()
        factory_templates = [t for t in templates if t.is_factory]

        outdated_names: list[str] = []
        for t in factory_templates:
            if not self._manager.check_version(t.id, current_hash):
                outdated_names.append(t.name)

        return VersionCheckResult(
            is_outdated=len(outdated_names) > 0,
            current_hash=current_hash,
            outdated_names=outdated_names,
        )

    def suppress_for_session(self) -> None:
        """Suppress version checks for the current session (user chose 'Ignore')."""
        self._suppressed = True
