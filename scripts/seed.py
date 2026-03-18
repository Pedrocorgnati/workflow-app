"""
Seed script — Workflow App
Execução: python scripts/seed.py

Popula o banco com dados de desenvolvimento cobrindo TODOS os estados de enum.
É idempotente: pode ser executado múltiplas vezes sem duplicar registros.

FK order:
  Nível 0: Template, AppConfig
  Nível 1: TemplateCommand, PipelineExecution
  Nível 2: CommandExecution
  Nível 3: ExecutionLog
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Garante que o pacote workflow_app está no path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from workflow_app.db.models import (
    AppConfig,
    Base,
    CommandExecution,
    ExecutionLog,
    PipelineExecution,
    Template,
    TemplateCommand,
)

# ---------------------------------------------------------------------------
# Configuração do banco
# ---------------------------------------------------------------------------

_DB_PATH = os.environ.get("DB_PATH") or str(
    Path.home() / ".workflow-app" / "workflow.db"
)
_ENGINE = create_engine(f"sqlite:///{_DB_PATH}", echo=False)
_SessionFactory = sessionmaker(bind=_ENGINE)

NOW = datetime.now(tz=timezone.utc).replace(tzinfo=None)


def _dt(days_ago: int = 0, hours_ago: int = 0) -> datetime:
    return NOW - timedelta(days=days_ago, hours=hours_ago)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _upsert_template(session, **kwargs) -> Template:
    """Insere ou atualiza Template pelo campo unique `name`."""
    obj = session.query(Template).filter_by(name=kwargs["name"]).first()
    if obj is None:
        obj = Template(**kwargs)
        session.add(obj)
    else:
        for k, v in kwargs.items():
            setattr(obj, k, v)
    session.flush()
    return obj


def _upsert_app_config(session, key: str, value: str) -> AppConfig:
    obj = session.query(AppConfig).filter_by(key=key).first()
    if obj is None:
        obj = AppConfig(key=key, value=value, updated_at=NOW)
        session.add(obj)
    else:
        obj.value = value
        obj.updated_at = NOW
    session.flush()
    return obj


# ---------------------------------------------------------------------------
# Nível 0 — Templates e AppConfig
# ---------------------------------------------------------------------------


def _seed_templates(session) -> dict[str, Template]:
    """Cria templates cobrindo os template_type: factory, custom, imported."""

    t1 = _upsert_template(
        session,
        name="Pipeline Completo SystemForge",
        description="Template de fábrica com todos os comandos do pipeline F1-F12.",
        template_type="factory",
        is_factory=True,
        sha256="a" * 64,
        created_at=_dt(30),
        updated_at=_dt(1),
    )

    t2 = _upsert_template(
        session,
        name="Pipeline Rápido (Custom)",
        description="Template customizado para projetos simples sem WBS completo.",
        template_type="custom",
        is_factory=False,
        sha256=None,
        created_at=_dt(10),
        updated_at=_dt(2),
    )

    t3 = _upsert_template(
        session,
        name="Pipeline Importado do Repositório",
        description="Template importado do repositório público de templates.",
        template_type="imported",
        is_factory=False,
        sha256="b" * 64,
        created_at=_dt(5),
        updated_at=_dt(0),
    )

    print(f"  Templates: {t1.name!r}, {t2.name!r}, {t3.name!r}")
    return {"factory": t1, "custom": t2, "imported": t3}


def _seed_app_configs(session) -> None:
    """Cria configurações de aplicação (chave-valor)."""

    configs = {
        "theme": "dark",
        "language": "pt-BR",
        "default_permission_mode": "acceptEdits",
        "auto_scroll_output": "true",
        "max_output_lines": "5000",
        "last_workspace_path": "/home/usuário/projetos/meu-app",
        "show_cost_estimates": "true",
        "telemetry_enabled": "false",
    }

    for key, value in configs.items():
        _upsert_app_config(session, key=key, value=value)

    print(f"  AppConfig: {len(configs)} entradas")


# ---------------------------------------------------------------------------
# Nível 1 — TemplateCommands e PipelineExecutions
# ---------------------------------------------------------------------------


def _seed_template_commands(session, templates: dict[str, Template]) -> None:
    """Cria comandos para cada template cobrindo os interaction_type e model_type."""

    # --- Template factory: pipeline completo
    factory_cmds = [
        dict(
            position=1,
            command_name="/project-json",
            model_type="haiku",
            interaction_type="com_interacao",
            estimated_seconds=30,
            is_optional=False,
        ),
        dict(
            position=2,
            command_name="/prd-create",
            model_type="opus",
            interaction_type="sem_interacao",
            estimated_seconds=120,
            is_optional=False,
        ),
        dict(
            position=3,
            command_name="/hld-create",
            model_type="opus",
            interaction_type="sem_interacao",
            estimated_seconds=90,
            is_optional=False,
        ),
        dict(
            position=4,
            command_name="/auto-flow modules",
            model_type="opus",
            interaction_type="com_confirmacao",
            estimated_seconds=300,
            is_optional=False,
        ),
        dict(
            position=5,
            command_name="/execute-task",
            model_type="sonnet",
            interaction_type="sem_interacao",
            estimated_seconds=180,
            is_optional=False,
        ),
        dict(
            position=6,
            command_name="/env-creation",
            model_type="haiku",
            interaction_type="com_interacao",
            estimated_seconds=60,
            is_optional=True,
        ),
    ]

    for cmd_data in factory_cmds:
        exists = (
            session.query(TemplateCommand)
            .filter_by(
                template_id=templates["factory"].id,
                position=cmd_data["position"],
            )
            .first()
        )
        if exists is None:
            session.add(
                TemplateCommand(template_id=templates["factory"].id, **cmd_data)
            )

    # --- Template custom: pipeline rápido (3 comandos)
    custom_cmds = [
        dict(
            position=1,
            command_name="/first-brief-create",
            model_type="opus",
            interaction_type="com_interacao",
            estimated_seconds=45,
            is_optional=False,
        ),
        dict(
            position=2,
            command_name="/execute-task",
            model_type="sonnet",
            interaction_type="sem_interacao",
            estimated_seconds=150,
            is_optional=False,
        ),
        dict(
            position=3,
            command_name="/final-review",
            model_type="sonnet",
            interaction_type="sem_interacao",
            estimated_seconds=60,
            is_optional=True,
        ),
    ]

    for cmd_data in custom_cmds:
        exists = (
            session.query(TemplateCommand)
            .filter_by(
                template_id=templates["custom"].id,
                position=cmd_data["position"],
            )
            .first()
        )
        if exists is None:
            session.add(
                TemplateCommand(template_id=templates["custom"].id, **cmd_data)
            )

    session.flush()
    total = len(factory_cmds) + len(custom_cmds)
    print(f"  TemplateCommands: {total} comandos em 2 templates")


def _seed_pipeline_executions(
    session, templates: dict[str, Template]
) -> list[PipelineExecution]:
    """
    Cria uma PipelineExecution para CADA status possível:
      nao_iniciado | executando | pausado | completo | interrompido
    """

    executions_data = [
        # nao_iniciado — pipeline criado, nunca iniciado
        dict(
            template_id=templates["factory"].id,
            project_config_path=".claude/projects/meu-projeto.json",
            status="nao_iniciado",
            permission_mode="acceptEdits",
            commands_total=6,
            commands_completed=0,
            commands_failed=0,
            commands_skipped=0,
            tokens_input=0,
            tokens_output=0,
            cost_usd=0.0,
            started_at=None,
            completed_at=None,
            created_at=_dt(0, 1),
        ),
        # executando — em andamento
        dict(
            template_id=templates["factory"].id,
            project_config_path=".claude/projects/app-ecommerce.json",
            status="executando",
            permission_mode="acceptEdits",
            commands_total=6,
            commands_completed=2,
            commands_failed=0,
            commands_skipped=0,
            tokens_input=12450,
            tokens_output=3800,
            cost_usd=0.18,
            started_at=_dt(0, 0),
            completed_at=None,
            created_at=_dt(0, 1),
        ),
        # pausado — interrompido pelo usuário temporariamente
        dict(
            template_id=templates["custom"].id,
            project_config_path=".claude/projects/landing-page.json",
            status="pausado",
            permission_mode="bypassPermissions",
            commands_total=3,
            commands_completed=1,
            commands_failed=0,
            commands_skipped=0,
            tokens_input=5200,
            tokens_output=1900,
            cost_usd=0.07,
            started_at=_dt(1),
            completed_at=None,
            created_at=_dt(1),
        ),
        # completo — finalizado com sucesso
        dict(
            template_id=templates["factory"].id,
            project_config_path=".claude/projects/saas-crm.json",
            status="completo",
            permission_mode="acceptEdits",
            commands_total=6,
            commands_completed=6,
            commands_failed=0,
            commands_skipped=0,
            tokens_input=98500,
            tokens_output=42100,
            cost_usd=1.85,
            started_at=_dt(3),
            completed_at=_dt(2),
            created_at=_dt(3),
        ),
        # interrompido — falhou durante execução
        dict(
            template_id=templates["imported"].id,
            project_config_path=".claude/projects/pipeline-importado.json",
            status="interrompido",
            permission_mode="default",
            commands_total=4,
            commands_completed=1,
            commands_failed=1,
            commands_skipped=0,
            tokens_input=8100,
            tokens_output=2300,
            cost_usd=0.11,
            started_at=_dt(5),
            completed_at=_dt(5),
            created_at=_dt(5),
        ),
    ]

    executions = []
    for data in executions_data:
        existing = (
            session.query(PipelineExecution)
            .filter_by(
                project_config_path=data["project_config_path"],
                status=data["status"],
            )
            .first()
        )
        if existing is None:
            obj = PipelineExecution(**data)
            session.add(obj)
            session.flush()
            executions.append(obj)
        else:
            executions.append(existing)

    statuses = [e.status for e in executions]
    print(f"  PipelineExecutions: {len(executions)} ({', '.join(statuses)})")
    return executions


# ---------------------------------------------------------------------------
# Nível 2 — CommandExecutions
# ---------------------------------------------------------------------------


def _seed_command_executions(
    session, executions: list[PipelineExecution]
) -> list[CommandExecution]:
    """
    Cria CommandExecutions cobrindo TODOS os status:
      pendente | executando | concluido | pulado | erro | incerto
    """

    pipe_completo = next(e for e in executions if e.status == "completo")
    pipe_interrompido = next(e for e in executions if e.status == "interrompido")
    pipe_executando = next(e for e in executions if e.status == "executando")

    cmd_data_list = [
        # Pipeline completo — concluido x5 + pulado x1
        dict(
            pipeline_id=pipe_completo.id,
            position=1,
            command_name="/project-json",
            model="haiku",
            interaction_type="com_interacao",
            status="concluido",
            is_optional=False,
            output_text="Arquivo .claude/projects/saas-crm.json criado com sucesso.",
            error_message=None,
            tokens_input=1200,
            tokens_output=450,
            elapsed_seconds=28,
            started_at=_dt(3),
            completed_at=_dt(3),
        ),
        dict(
            pipeline_id=pipe_completo.id,
            position=2,
            command_name="/prd-create",
            model="opus",
            interaction_type="sem_interacao",
            status="concluido",
            is_optional=False,
            output_text="PRD gerado com 12 requisitos funcionais e 4 não-funcionais.",
            error_message=None,
            tokens_input=18500,
            tokens_output=9200,
            elapsed_seconds=115,
            started_at=_dt(3),
            completed_at=_dt(3),
        ),
        dict(
            pipeline_id=pipe_completo.id,
            position=3,
            command_name="/hld-create",
            model="opus",
            interaction_type="sem_interacao",
            status="concluido",
            is_optional=False,
            output_text="HLD criado com diagrama de arquitetura e 8 entidades.",
            error_message=None,
            tokens_input=22000,
            tokens_output=11500,
            elapsed_seconds=98,
            started_at=_dt(2),
            completed_at=_dt(2),
        ),
        dict(
            pipeline_id=pipe_completo.id,
            position=4,
            command_name="/auto-flow modules",
            model="opus",
            interaction_type="com_confirmacao",
            status="concluido",
            is_optional=False,
            output_text="12 módulos e 48 tasks gerados no WBS.",
            error_message=None,
            tokens_input=35200,
            tokens_output=14800,
            elapsed_seconds=298,
            started_at=_dt(2),
            completed_at=_dt(2),
        ),
        dict(
            pipeline_id=pipe_completo.id,
            position=5,
            command_name="/execute-task",
            model="sonnet",
            interaction_type="sem_interacao",
            status="concluido",
            is_optional=False,
            output_text="Todas as tasks do módulo 01 executadas com sucesso.",
            error_message=None,
            tokens_input=18600,
            tokens_output=5900,
            elapsed_seconds=182,
            started_at=_dt(2),
            completed_at=_dt(2),
        ),
        dict(
            pipeline_id=pipe_completo.id,
            position=6,
            command_name="/env-creation",
            model="haiku",
            interaction_type="com_interacao",
            status="pulado",
            is_optional=True,
            output_text=None,
            error_message=None,
            tokens_input=0,
            tokens_output=0,
            elapsed_seconds=0,
            started_at=None,
            completed_at=None,
        ),
        # Pipeline interrompido — concluido + erro + pendente + incerto
        dict(
            pipeline_id=pipe_interrompido.id,
            position=1,
            command_name="/first-brief-create",
            model="opus",
            interaction_type="com_interacao",
            status="concluido",
            is_optional=False,
            output_text="INTAKE.md criado com briefing inicial do projeto.",
            error_message=None,
            tokens_input=4500,
            tokens_output=1800,
            elapsed_seconds=55,
            started_at=_dt(5),
            completed_at=_dt(5),
        ),
        dict(
            pipeline_id=pipe_interrompido.id,
            position=2,
            command_name="/prd-create",
            model="opus",
            interaction_type="sem_interacao",
            status="erro",
            is_optional=False,
            output_text=None,
            error_message="Rate limit atingido na API Anthropic. Tente novamente em 60 segundos.",
            tokens_input=3600,
            tokens_output=500,
            elapsed_seconds=12,
            started_at=_dt(5),
            completed_at=_dt(5),
        ),
        dict(
            pipeline_id=pipe_interrompido.id,
            position=3,
            command_name="/hld-create",
            model="opus",
            interaction_type="sem_interacao",
            status="pendente",
            is_optional=False,
            output_text=None,
            error_message=None,
            tokens_input=0,
            tokens_output=0,
            elapsed_seconds=0,
            started_at=None,
            completed_at=None,
        ),
        dict(
            pipeline_id=pipe_interrompido.id,
            position=4,
            command_name="/validate-pipeline",
            model="sonnet",
            interaction_type="sem_interacao",
            status="incerto",
            is_optional=True,
            output_text=None,
            error_message="Timeout após 300s. Status da execução não confirmado.",
            tokens_input=0,
            tokens_output=0,
            elapsed_seconds=300,
            started_at=_dt(5),
            completed_at=_dt(5),
        ),
        # Pipeline executando — concluido + executando
        dict(
            pipeline_id=pipe_executando.id,
            position=1,
            command_name="/project-json",
            model="haiku",
            interaction_type="com_interacao",
            status="concluido",
            is_optional=False,
            output_text="Arquivo .claude/projects/app-ecommerce.json criado.",
            error_message=None,
            tokens_input=1800,
            tokens_output=620,
            elapsed_seconds=22,
            started_at=_dt(0, 1),
            completed_at=_dt(0, 1),
        ),
        dict(
            pipeline_id=pipe_executando.id,
            position=2,
            command_name="/prd-create",
            model="opus",
            interaction_type="sem_interacao",
            status="executando",
            is_optional=False,
            output_text=None,
            error_message=None,
            tokens_input=10650,
            tokens_output=3180,
            elapsed_seconds=0,
            started_at=_dt(0, 0),
            completed_at=None,
        ),
    ]

    created: list[CommandExecution] = []
    for data in cmd_data_list:
        existing = (
            session.query(CommandExecution)
            .filter_by(
                pipeline_id=data["pipeline_id"],
                position=data["position"],
            )
            .first()
        )
        if existing is None:
            obj = CommandExecution(**data)
            session.add(obj)
            session.flush()
            created.append(obj)
        else:
            created.append(existing)

    statuses_found = sorted({c.status for c in created})
    print(f"  CommandExecutions: {len(created)} ({', '.join(statuses_found)})")
    return created


# ---------------------------------------------------------------------------
# Nível 3 — ExecutionLogs
# ---------------------------------------------------------------------------


def _seed_execution_logs(
    session,
    executions: list[PipelineExecution],
    commands: list[CommandExecution],
) -> None:
    """Cria logs de execução cobrindo os levels: info, warning, error, debug, success."""

    pipe_completo = next(e for e in executions if e.status == "completo")
    pipe_interrompido = next(e for e in executions if e.status == "interrompido")

    cmd_concluido = next(
        (c for c in commands if c.pipeline_id == pipe_completo.id and c.position == 1),
        None,
    )
    cmd_erro = next(
        (c for c in commands if c.pipeline_id == pipe_interrompido.id and c.status == "erro"),
        None,
    )

    logs_data = [
        dict(
            pipeline_id=pipe_completo.id,
            command_execution_id=cmd_concluido.id if cmd_concluido else None,
            level="info",
            message="Iniciando execução do comando /project-json.",
            summary_content=None,
            export_path=None,
            created_at=_dt(3),
        ),
        dict(
            pipeline_id=pipe_completo.id,
            command_execution_id=cmd_concluido.id if cmd_concluido else None,
            level="success",
            message="Comando /project-json concluído. Arquivo gerado em .claude/projects/saas-crm.json.",
            summary_content="Template V3 criado com 6 módulos planejados.",
            export_path=".claude/projects/saas-crm.json",
            created_at=_dt(3),
        ),
        dict(
            pipeline_id=pipe_completo.id,
            command_execution_id=None,
            level="debug",
            message="Tokens acumulados: input=1200 output=450 custo=$0.01.",
            summary_content=None,
            export_path=None,
            created_at=_dt(3),
        ),
        dict(
            pipeline_id=pipe_completo.id,
            command_execution_id=None,
            level="warning",
            message="Comando /env-creation (opcional) foi pulado pelo usuário.",
            summary_content=None,
            export_path=None,
            created_at=_dt(2),
        ),
        dict(
            pipeline_id=pipe_completo.id,
            command_execution_id=None,
            level="success",
            message="Pipeline finalizado. 5 de 6 comandos executados com sucesso (1 pulado).",
            summary_content="Custo total: $1.85 | Tokens: 98.500 input / 42.100 output",
            export_path=None,
            created_at=_dt(2),
        ),
        dict(
            pipeline_id=pipe_interrompido.id,
            command_execution_id=cmd_erro.id if cmd_erro else None,
            level="error",
            message="Falha no /prd-create: Rate limit atingido na API Anthropic.",
            summary_content=None,
            export_path=None,
            created_at=_dt(5),
        ),
        dict(
            pipeline_id=pipe_interrompido.id,
            command_execution_id=None,
            level="warning",
            message="Pipeline interrompido após erro. Comandos restantes não serão executados.",
            summary_content=None,
            export_path=None,
            created_at=_dt(5),
        ),
    ]

    count = 0
    for data in logs_data:
        existing = (
            session.query(ExecutionLog)
            .filter_by(
                pipeline_id=data["pipeline_id"],
                message=data["message"],
            )
            .first()
        )
        if existing is None:
            session.add(ExecutionLog(**data))
            count += 1

    session.flush()
    levels = sorted({d["level"] for d in logs_data})
    print(f"  ExecutionLogs: {count} novos ({', '.join(levels)})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("Iniciando seed do Workflow App...")
    print(f"Banco de dados: {_DB_PATH}\n")

    # Garante que as tabelas existem
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(_ENGINE, checkfirst=True)

    db = _SessionFactory()
    try:
        print("Nível 0 — Entidades base:")
        templates = _seed_templates(db)
        _seed_app_configs(db)

        print("\nNível 1 — Entidades com FK para Nível 0:")
        _seed_template_commands(db, templates)
        executions = _seed_pipeline_executions(db, templates)

        print("\nNível 2 — CommandExecutions:")
        commands = _seed_command_executions(db, executions)

        print("\nNível 3 — ExecutionLogs:")
        _seed_execution_logs(db, executions, commands)

        db.commit()
        print("\nSeed concluído com sucesso!")
        print("\nResumo de registros:")
        print(f"  Templates:          {db.query(Template).count()}")
        print(f"  TemplateCommands:   {db.query(TemplateCommand).count()}")
        print(f"  PipelineExecutions: {db.query(PipelineExecution).count()}")
        print(f"  CommandExecutions:  {db.query(CommandExecution).count()}")
        print(f"  ExecutionLogs:      {db.query(ExecutionLog).count()}")
        print(f"  AppConfigs:         {db.query(AppConfig).count()}")

    except Exception as exc:
        db.rollback()
        print(f"\nErro no seed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
