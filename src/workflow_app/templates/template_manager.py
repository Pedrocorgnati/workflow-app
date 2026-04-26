"""
TemplateManager — CRUD for pipeline templates (module-05/TASK-1).

Manages factory templates (read-only) and custom templates (create/delete).
Uses DatabaseManager.get_session() for all DB operations.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from workflow_app.db.database_manager import db_manager
from workflow_app.db.models import Template, TemplateCommand
from workflow_app.domain import (
    CommandSpec,
    TemplateDTO,
    TemplateType,
)
from workflow_app.templates._mapping import (
    db_to_effort,
    effort_to_db,
    interaction_to_db,
    interaction_to_ui,
    model_name_to_db,
    model_type_to_name,
)

logger = logging.getLogger(__name__)


class TemplateManager:
    """
    Manages pipeline templates (factory + user-created).

    Factory templates are read-only (cannot be deleted).
    Custom templates support create and delete.
    """

    def __init__(self, database_manager=None) -> None:
        self._db = database_manager or db_manager

    _FACTORY_ORDER = [
        "Daily",
        "JSON",
        "Brief: New",
        "Brief: Feature",
        "Modules",
        "Deploy",
        "Marketing",
        "Business",
    ]

    def list_templates(self) -> list[TemplateDTO]:
        """Return all templates as TemplateDTO (without full command lists).

        Orders: factory templates in predefined order first, then custom alphabetically.
        """
        with self._db.get_session() as session:
            stmt = select(Template).order_by(
                Template.is_factory.desc(),
                Template.name.asc(),
            )
            templates = session.execute(stmt).scalars().all()

            def _sort_key(t: Template):
                if t.is_factory:
                    try:
                        return (0, self._FACTORY_ORDER.index(t.name))
                    except ValueError:
                        return (0, len(self._FACTORY_ORDER))
                return (1, t.name)

            return [
                TemplateDTO(
                    id=t.id,
                    name=t.name,
                    description=t.description or "",
                    template_type=TemplateType.FACTORY if t.is_factory else TemplateType.CUSTOM,
                    is_factory=t.is_factory,
                    sha256=t.sha256,
                    commands=[],  # not loaded in list view
                )
                for t in sorted(templates, key=_sort_key)
            ]

    def load_template(self, template_id: int) -> TemplateDTO:
        """Load a template with its full command list.

        Raises:
            ValueError: if template_id not found.
        """
        with self._db.get_session() as session:
            template = session.get(Template, template_id)
            if template is None:
                raise ValueError(f"Template id={template_id} não encontrado no banco")

            commands = sorted(template.commands, key=lambda c: c.position)
            specs = [
                CommandSpec(
                    name=cmd.command_name,
                    model=model_type_to_name(cmd.model_type),
                    interaction_type=interaction_to_ui(cmd.interaction_type),
                    position=cmd.position,
                    is_optional=cmd.is_optional,
                    effort=db_to_effort(cmd.effort_level),
                )
                for cmd in commands
            ]

            return TemplateDTO(
                id=template.id,
                name=template.name,
                description=template.description or "",
                template_type=TemplateType.FACTORY if template.is_factory else TemplateType.CUSTOM,
                is_factory=template.is_factory,
                sha256=template.sha256,
                commands=specs,
            )

    def save_custom_template(
        self,
        name: str,
        description: str,
        commands: list[CommandSpec],
        sha256: str | None = None,
    ) -> int:
        """Persist a new custom template.

        Args:
            name: unique template name
            description: optional description
            commands: list of CommandSpec (min 1)
            sha256: SHA-256 hash of CLAUDE.md at creation time

        Returns:
            int: id of the created template

        Raises:
            ValueError: empty name, duplicate name, or empty commands
        """
        self._validate_save(name, commands)

        with self._db.get_session() as session:
            existing = session.execute(
                select(Template).where(Template.name == name)
            ).scalar_one_or_none()
            if existing is not None:
                raise ValueError(f"Nome de template já existente: '{name}'")

            template = Template(
                name=name,
                description=description,
                template_type=TemplateType.CUSTOM.value,
                is_factory=False,
                sha256=sha256,
            )
            session.add(template)
            session.flush()

            for spec in commands:
                cmd = TemplateCommand(
                    template_id=template.id,
                    command_name=spec.name,
                    model_type=model_name_to_db(spec.model),
                    interaction_type=interaction_to_db(spec.interaction_type),
                    position=spec.position,
                    is_optional=spec.is_optional,
                    effort_level=effort_to_db(spec.effort),
                )
                session.add(cmd)

            session.commit()
            return template.id

    # Alias for API compatibility (documented as save_template in PRD EP015)
    save_template = save_custom_template

    def update_custom_template(
        self,
        template_id: int,
        commands: list[CommandSpec],
    ) -> None:
        """Replace all commands of an existing custom template.

        Raises:
            PermissionError: if template is factory
            ValueError: if template not found or commands empty
        """
        if not commands:
            raise ValueError("Template deve ter pelo menos 1 comando")
        with self._db.get_session() as session:
            template = session.get(Template, template_id)
            if template is None:
                raise ValueError(f"Template id={template_id} não encontrado")
            if template.is_factory:
                raise PermissionError("Templates de fábrica não podem ser editados")
            # Remove old commands
            for cmd in list(template.commands):
                session.delete(cmd)
            session.flush()
            # Insert new commands
            for spec in commands:
                cmd = TemplateCommand(
                    template_id=template.id,
                    command_name=spec.name,
                    model_type=model_name_to_db(spec.model),
                    interaction_type=interaction_to_db(spec.interaction_type),
                    position=spec.position,
                    is_optional=spec.is_optional,
                    effort_level=effort_to_db(spec.effort),
                )
                session.add(cmd)
            session.commit()

    def delete_template(self, template_id: int) -> None:
        """Delete a custom template.

        Raises:
            PermissionError: if template is factory (is_factory=True)
            ValueError: if template not found
        """
        with self._db.get_session() as session:
            template = session.get(Template, template_id)
            if template is None:
                raise ValueError(f"Template id={template_id} não encontrado")
            if template.is_factory:
                raise PermissionError(
                    f"Templates de fábrica não podem ser deletados: '{template.name}'"
                )
            session.delete(template)
            session.commit()

    def check_version(self, template_id: int, current_hash: str) -> bool:
        """Check if template's sha256 matches the current CLAUDE.md hash.

        Returns True if matching (up-to-date), False if divergent.
        """
        with self._db.get_session() as session:
            template = session.get(Template, template_id)
            if template is None or template.sha256 is None:
                return False
            return template.sha256 == current_hash

    def update_sha256(self, template_id: int, new_hash: str) -> None:
        """Update sha256 for a template (used by refresh_factory_templates)."""
        with self._db.get_session() as session:
            template = session.get(Template, template_id)
            if template is not None:
                template.sha256 = new_hash
                session.commit()

    @staticmethod
    def _validate_save(name: str, commands: list[CommandSpec]) -> None:
        if not name or not name.strip():
            raise ValueError("Nome do template não pode ser vazio")
        if not commands:
            raise ValueError("Template deve ter pelo menos 1 comando")
