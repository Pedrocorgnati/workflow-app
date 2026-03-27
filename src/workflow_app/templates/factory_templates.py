"""
Factory template definitions and seeding.

Defines 9 read-only factory templates matching the header buttons:
  1. JSON           — /project-json (1 command)
  2. Brief: New     — Projeto novo completo F1→F3 (~27 commands)
  3. Brief: Feature — Feature em projeto existente (~27 commands)
  4. Modules        — Pipeline F4 (~8 commands)
  5. Deploy         — CI/CD, infra, pre-deploy, staging, monitoring (~10 commands)
  6. Daily          — Daily tasks pipeline (5 commands)
  7. Marketing      — Docs, portfolio, LinkedIn, Instagram, handoff (~6 commands)
  8. Business       — Product brief, SOW, budget (~6 commands)

QA templates (5 per stack) are available via the QA modal but not seeded
as factory templates in the DB (too many commands, stack-specific).

The WBS template is dynamic and not stored in the DB.

Functions:
  seed_factory_templates()    — idempotent insert on first run
  refresh_factory_templates() — re-applies commands with new SHA-256
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from workflow_app.db.models import Template, TemplateCommand
from workflow_app.domain import CommandSpec, TemplateType
from workflow_app.templates._mapping import interaction_to_db, model_name_to_db
from workflow_app.templates.quick_templates import (
    TEMPLATE_BLOG,
    TEMPLATE_BRIEF_FEATURE,
    TEMPLATE_BRIEF_NEW,
    TEMPLATE_BUSINESS,
    TEMPLATE_DAILY,
    TEMPLATE_DEPLOY,
    TEMPLATE_JSON,
    TEMPLATE_MICRO_ARCHITECTURE,
    TEMPLATE_MKT,
    TEMPLATE_MODULES,
)

if TYPE_CHECKING:
    from workflow_app.db.database_manager import DatabaseManager

logger = logging.getLogger(__name__)

# ─── Factory map: name → (description, commands) ───────────────────────────── #

FACTORY_TEMPLATES: dict[str, tuple[str, list[CommandSpec]]] = {
    "JSON": (
        "Apenas /project-json. 1 comando.",
        TEMPLATE_JSON,
    ),
    "Brief: New": (
        "Projeto novo completo F1→F3: intake, PRD, HLD, LLD, research, design. ~27 comandos.",
        TEMPLATE_BRIEF_NEW,
    ),
    "Brief: Feature": (
        "Feature em projeto existente F1→F3: intake, PRD, HLD, LLD, research, design. ~27 comandos.",
        TEMPLATE_BRIEF_FEATURE,
    ),
    "Modules": (
        "Pipeline F4: create-core → blueprints → variants → structure → coverage → overview → review. ~8 comandos.",
        TEMPLATE_MODULES,
    ),
    "Deploy": (
        "CI/CD, infra, pre-deploy, SLO, staging, monitoring, post-deploy, changelog, deploy-flow. ~10 comandos.",
        TEMPLATE_DEPLOY,
    ),
    "Daily": (
        "Daily tasks: scan → plan → do → validate → review. 5 comandos.",
        TEMPLATE_DAILY,
    ),
    "Marketing": (
        "Docs, portfolio, LinkedIn, Instagram, publish, handoff. ~6 comandos.",
        TEMPLATE_MKT,
    ),
    "Business": (
        "Product brief, SOW, budget, PDFs, JSON upload. ~6 comandos.",
        TEMPLATE_BUSINESS,
    ),
    "Micro-Architecture": (
        "Brief de feature + micro-arquitetura pontual: feature-brief → intake → micro-architecture + review. 5 comandos.",
        TEMPLATE_MICRO_ARCHITECTURE,
    ),
    "Blog SEO": (
        "Pipeline completo de blog SEO: estratégia → keywords → clusters → artigos → review → deploy. 14 comandos.",
        TEMPLATE_BLOG,
    ),
}

# ─── Old template names to delete during migration ──────────────────────────── #

_OLD_TEMPLATE_NAMES = [
    "Sistema Novo Completo",
    "Sistema Novo",
    "Feature Grande",
    "Feature com PRD",
    "Feature Pequena",
    "Feature com Micro Architecture",
    "Deploy Rápido",
]


# ─── Seeding functions ─────────────────────────────────────────────────────── #


def seed_factory_templates(
    db_manager: DatabaseManager,
    sha256: str | None = None,
) -> None:
    """Insert factory templates if they don't exist yet.

    Idempotent: checks by name before inserting. Silent if already present.
    Also cleans up old template names from previous versions.

    Args:
        db_manager: application DatabaseManager instance
        sha256: SHA-256 hash of CLAUDE.md at seed time (None if not found)
    """
    with db_manager.get_session() as session:
        # Clean up old templates from previous versions
        for old_name in _OLD_TEMPLATE_NAMES:
            old_row = session.execute(
                select(Template).where(Template.name == old_name)
            ).scalar_one_or_none()
            if old_row is not None:
                session.delete(old_row)
                session.flush()

        for name, (description, commands) in FACTORY_TEMPLATES.items():
            existing = session.execute(
                select(Template).where(Template.name == name)
            ).scalar_one_or_none()

            if existing is not None:
                continue

            template = Template(
                name=name,
                description=description,
                template_type=TemplateType.FACTORY.value,
                is_factory=True,
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
                )
                session.add(cmd)

        session.commit()
    logger.info("Factory templates seeded (%d definitions).", len(FACTORY_TEMPLATES))


def refresh_factory_templates(
    db_manager: DatabaseManager,
    new_hash: str,
) -> None:
    """Re-apply factory template commands with a new SHA-256 hash.

    Deletes all commands from factory templates, re-inserts the current
    definitions and updates sha256. Also cleans up old template names.

    Args:
        db_manager: application DatabaseManager instance
        new_hash: new SHA-256 hash of CLAUDE.md
    """
    with db_manager.get_session() as session:
        # Clean up old templates
        for old_name in _OLD_TEMPLATE_NAMES:
            old_row = session.execute(
                select(Template).where(Template.name == old_name)
            ).scalar_one_or_none()
            if old_row is not None:
                session.delete(old_row)
                session.flush()

        for name, (description, commands) in FACTORY_TEMPLATES.items():
            template = session.execute(
                select(Template).where(Template.name == name)
            ).scalar_one_or_none()

            if template is None:
                template = Template(
                    name=name,
                    description=description,
                    template_type=TemplateType.FACTORY.value,
                    is_factory=True,
                    sha256=new_hash,
                )
                session.add(template)
                session.flush()
            else:
                for cmd in list(template.commands):
                    session.delete(cmd)
                session.flush()
                template.sha256 = new_hash

            for spec in commands:
                cmd = TemplateCommand(
                    template_id=template.id,
                    command_name=spec.name,
                    model_type=model_name_to_db(spec.model),
                    interaction_type=interaction_to_db(spec.interaction_type),
                    position=spec.position,
                    is_optional=spec.is_optional,
                )
                session.add(cmd)

        session.commit()
    logger.info("Factory templates refreshed with new hash.")
