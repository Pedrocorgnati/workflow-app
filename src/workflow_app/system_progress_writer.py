"""
SystemProgressWriter — gera e mantém SYSTEM-PROGRESS.md (module-07/TASK-1).

Responsável pelo ciclo de vida do SYSTEM-PROGRESS.md:
  - generate()         — cria o arquivo com todas as seções; idempotente
  - mark_completed()   — marca [ ] → [x]
  - mark_error()       — marca [ ] → [!] com mensagem inline
  - expand_progress()  — adiciona seções F5-F7 com módulos reais do WBS
  - add_deploy_section() — acrescenta seção F11 de deploy

Substitui /deploy-flow para uso programático.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from workflow_app.domain import CommandSpec
from workflow_app.signal_bus import signal_bus

logger = logging.getLogger(__name__)

# ─── Marcadores de status ────────────────────────────────────────────────── #
_MARK_PENDING = "[ ]"
_MARK_DONE = "[x]"
_MARK_ERROR = "[!]"

# Separador de bloco (mesmo formato do SYSTEM_PROGRESS_TEMPLATE.md)
_BLOCK_SEP = "--------------------------------"

# ─── Templates de seção para expand_progress ────────────────────────────── #
_F11_SECTION = (
    "## F11: DEPLOY\n\n"
    f"{_BLOCK_SEP}\n[ ]\n/model Sonnet\n/ci-cd-create\n"
    f"{_BLOCK_SEP}\n[ ]\n/model Sonnet\n/pre-deploy-testing\n"
    f"{_BLOCK_SEP}\n[ ]\n/model Sonnet\n/post-deploy-verify\n"
    f"{_BLOCK_SEP}\n[ ]\n/model Haiku\n/changelog-create\n"
)


class SystemProgressWriter:
    """
    Gera e mantém SYSTEM-PROGRESS.md em docs_root.

    O workflow-app é autoridade sobre este arquivo — substitui
    /deploy-flow do SystemForge CLI.

    Todas as operações são idempotentes e preservam marcadores existentes.

    Usage::

        writer = SystemProgressWriter()
        writer.generate(commands, docs_root="/path/to/docs", project_name="Meu Projeto")
        writer.mark_completed("prd-create", "/path/to/docs")
        writer.expand_progress(["module-01-setup"], "/path/to/docs")
    """

    # ──────────────────────────────────────────────────────────────────── #
    # API Pública
    # ──────────────────────────────────────────────────────────────────── #

    def generate(
        self,
        commands: list[CommandSpec],
        docs_root: str,
        project_name: str = "Projeto",
        config_path: str = ".claude/project.json",
    ) -> None:
        """
        Cria o SYSTEM-PROGRESS.md com todos os comandos listados.

        Se o arquivo já existir, não sobrescreve — usa merge idempotente
        para adicionar apenas comandos ausentes.

        Args:
            commands: Lista ordenada de CommandSpec.
            docs_root: Diretório onde o arquivo será criado.
            project_name: Nome do projeto para o cabeçalho.
            config_path: Caminho do project.json para o cabeçalho.
        """
        target = Path(docs_root) / "SYSTEM-PROGRESS.md"
        content = self._build_initial_content(commands, project_name, config_path)

        try:
            if target.exists():
                self._idempotency_merge(target, commands)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                logger.info("SYSTEM-PROGRESS.md criado em %s", target)
        except PermissionError as exc:
            logger.error("Sem permissão para escrever SYSTEM-PROGRESS.md: %s", exc)
            signal_bus.toast_requested.emit(
                "Sem permissão para escrever SYSTEM-PROGRESS.md", "error"
            )
            raise

    def mark_completed(self, command_name: str, docs_root: str) -> None:
        """
        Marca o comando como concluído ([ ] → [x]).

        Args:
            command_name: Nome do comando sem barra (ex: "prd-create").
            docs_root: Diretório do SYSTEM-PROGRESS.md.
        """
        self._update_mark(
            command_name=command_name,
            docs_root=docs_root,
            new_mark=_MARK_DONE,
            suffix="",
        )
        logger.info("Comando '%s' marcado como concluído", command_name)

    def mark_error(
        self,
        command_name: str,
        error_msg: str,
        docs_root: str,
    ) -> None:
        """
        Marca o comando como erro ([!] com mensagem inline).

        Args:
            command_name: Nome do comando sem barra (ex: "hld-create").
            error_msg: Mensagem curta do erro para exibição inline.
            docs_root: Diretório do SYSTEM-PROGRESS.md.
        """
        self._update_mark(
            command_name=command_name,
            docs_root=docs_root,
            new_mark=_MARK_ERROR,
            suffix=f"  ← Erro: {error_msg}",
        )
        logger.warning("Comando '%s' marcou erro: %s", command_name, error_msg)

    def get_status(self, command_name: str, docs_root: str) -> str | None:
        """
        Retorna o estado atual do comando no SYSTEM-PROGRESS.md.

        Args:
            command_name: Nome do comando sem barra (ex: "prd-create").
            docs_root: Diretório do SYSTEM-PROGRESS.md.

        Returns:
            "pending", "completed", "error", ou None se não encontrado.
        """
        target = Path(docs_root) / "SYSTEM-PROGRESS.md"
        if not target.exists():
            return None

        text = target.read_text(encoding="utf-8")
        pattern = re.compile(
            r"^\[([x !])\](\n/model [^\n]+)?\n/?"
            + re.escape(command_name)
            + r"[^\n]*",
            re.MULTILINE,
        )
        match = pattern.search(text)
        if not match:
            return None

        marker = match.group(1)
        if marker == "x":
            return "completed"
        elif marker == "!":
            return "error"
        return "pending"

    def expand_progress(
        self,
        new_modules: list[str],
        docs_root: str,
        wbs_root: str = "output/wbs",
        project_slug: str = "projeto",
    ) -> None:
        """
        Adiciona seções F5-F7 ao SYSTEM-PROGRESS.md com os módulos do WBS.

        Equivalente ao que o pipeline fazia manualmente.
        Idempotente: não duplica seções já presentes.

        Args:
            new_modules: Slugs de módulo (ex: ["module-01-setup"]).
            docs_root: Diretório do SYSTEM-PROGRESS.md.
            wbs_root: Root do WBS para construir caminhos.
            project_slug: Slug do projeto para compor o caminho.
        """
        target = Path(docs_root) / "SYSTEM-PROGRESS.md"
        if not target.exists():
            logger.warning(
                "SYSTEM-PROGRESS.md não encontrado — expand_progress ignorado"
            )
            return

        existing = target.read_text(encoding="utf-8")
        sections_to_add: list[str] = []

        if "## F5" not in existing:
            f5_lines = [
                f"{_BLOCK_SEP}\n[ ]\n/model Sonnet\n"
                f"/auto-flow create {wbs_root}/{project_slug}/modules/{mod}"
                for mod in new_modules
            ]
            sections_to_add.append(
                "## F5: WBS+ (Otimização de Planejamento)\n\n"
                + "\n".join(f5_lines)
                + "\n"
            )

        if "## F6" not in existing:
            sections_to_add.append(
                f"## F6: BUSINESS\n\n"
                f"{_BLOCK_SEP}\n[ ]\n/model Opus\n/auto-flow documents\n"
            )

        if "## F7" not in existing:
            f7_lines = [
                f"{_BLOCK_SEP}\n[ ]\n/model Sonnet\n"
                f"/auto-flow execute {wbs_root}/{project_slug}/modules/{mod}"
                for mod in new_modules
            ]
            sections_to_add.append(
                "## F7: EXECUTION\n\n"
                + "\n".join(f7_lines)
                + "\n"
            )

        if not sections_to_add:
            logger.info("expand_progress: seções F5-F7 já existem, nada a adicionar")
            return

        try:
            appended = (
                existing.rstrip()
                + "\n\n---\n\n"
                + "\n\n---\n\n".join(sections_to_add)
            )
            target.write_text(appended, encoding="utf-8")
            logger.info(
                "expand_progress: %d seção(ões) adicionadas ao SYSTEM-PROGRESS.md",
                len(sections_to_add),
            )
        except PermissionError as exc:
            logger.error("Sem permissão para expandir SYSTEM-PROGRESS.md: %s", exc)
            signal_bus.toast_requested.emit(
                "Sem permissão para escrever SYSTEM-PROGRESS.md", "error"
            )
            raise

    def add_deploy_section(self, docs_root: str) -> None:
        """
        Adiciona seção F11 (Deploy) ao SYSTEM-PROGRESS.md.

        Equivalente ao que /deploy-flow configurava manualmente.
        Idempotente: não duplica se F11 já existe.

        Args:
            docs_root: Diretório do SYSTEM-PROGRESS.md.
        """
        target = Path(docs_root) / "SYSTEM-PROGRESS.md"
        if not target.exists():
            logger.warning(
                "SYSTEM-PROGRESS.md não encontrado — add_deploy_section ignorado"
            )
            return

        existing = target.read_text(encoding="utf-8")
        if "## F11" in existing:
            logger.info("add_deploy_section: F11 já presente, ignorando")
            return

        try:
            appended = existing.rstrip() + "\n\n---\n\n" + _F11_SECTION
            target.write_text(appended, encoding="utf-8")
            logger.info("Seção F11 adicionada ao SYSTEM-PROGRESS.md")
        except PermissionError as exc:
            logger.error("Sem permissão para adicionar F11: %s", exc)
            signal_bus.toast_requested.emit(
                "Sem permissão para escrever SYSTEM-PROGRESS.md", "error"
            )
            raise

    # ──────────────────────────────────────────────────────────────────── #
    # Helpers privados
    # ──────────────────────────────────────────────────────────────────── #

    def _build_initial_content(
        self,
        commands: list[CommandSpec],
        project_name: str,
        config_path: str,
    ) -> str:
        lines: list[str] = [
            f"# System Progress — {project_name}",
            "",
            f"**Projeto:** {project_name}",
            f"**Config:** {config_path}",
            f"**Iniciado:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "---",
            "",
        ]

        # Agrupar por fase (CommandSpec pode não ter .phase — usa "F?")
        phases: dict[str, list[CommandSpec]] = {}
        for cmd in commands:
            phase = getattr(cmd, "phase", None) or "F?"
            phases.setdefault(phase, []).append(cmd)

        for phase, cmds in phases.items():
            lines.append(f"## {phase}")
            lines.append("")
            for cmd in cmds:
                lines.append(_BLOCK_SEP)
                model_val = cmd.model.value if hasattr(cmd.model, "value") else str(cmd.model)
                lines.append(_MARK_PENDING)
                lines.append(f"/model {model_val}")
                lines.append(f"/{cmd.name}")
            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def _update_mark(
        self,
        command_name: str,
        docs_root: str,
        new_mark: str,
        suffix: str,
    ) -> None:
        """
        Localiza o bloco '[ ]\\n[/model ...]\\n/command-name' e substitui o marcador.

        O formato do SYSTEM-PROGRESS.md usa linhas separadas:
          [ ]
          /model Sonnet
          /command-name
        """
        target = Path(docs_root) / "SYSTEM-PROGRESS.md"
        if not target.exists():
            logger.warning(
                "SYSTEM-PROGRESS.md não encontrado em %s — mark ignorado", docs_root
            )
            return

        try:
            text = target.read_text(encoding="utf-8")
            # Match: marker_line, optional /model line, then /command-name line
            pattern = re.compile(
                r"^\[[ x!]\](\n/model [^\n]+)?\n/?"
                + re.escape(command_name)
                + r"[^\n]*",
                re.MULTILINE,
            )

            def _replacer(m: re.Match) -> str:
                model_part = m.group(1) or ""
                return f"{new_mark}{model_part}\n/{command_name}{suffix}"

            new_text, n = pattern.subn(_replacer, text)
            if n == 0:
                logger.warning(
                    "Comando '/%s' não encontrado em SYSTEM-PROGRESS.md", command_name
                )
                return
            target.write_text(new_text, encoding="utf-8")
        except PermissionError as exc:
            logger.error("Sem permissão para atualizar SYSTEM-PROGRESS.md: %s", exc)
            signal_bus.toast_requested.emit(
                "Sem permissão para escrever SYSTEM-PROGRESS.md", "error"
            )
            raise

    def _idempotency_merge(
        self,
        target: Path,
        commands: list[CommandSpec],
    ) -> None:
        """Adiciona ao arquivo apenas comandos ainda não presentes."""
        existing = target.read_text(encoding="utf-8")
        new_lines: list[str] = []
        for cmd in commands:
            if f"/{cmd.name}" not in existing:
                model_val = cmd.model.value if hasattr(cmd.model, "value") else str(cmd.model)
                new_lines.append(_BLOCK_SEP)
                new_lines.append(_MARK_PENDING)
                new_lines.append(f"/model {model_val}")
                new_lines.append(f"/{cmd.name}")

        if new_lines:
            appended = existing.rstrip() + "\n\n" + "\n".join(new_lines) + "\n"
            target.write_text(appended, encoding="utf-8")
            added_count = sum(1 for ln in new_lines if ln.startswith("/") and not ln.startswith("/model"))
            logger.info(
                "%d novo(s) comando(s) adicionado(s) ao SYSTEM-PROGRESS.md",
                added_count,
            )
