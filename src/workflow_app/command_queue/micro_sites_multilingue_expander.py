"""Expander for the ``queue-btn-publish-micro-sites-multilingue`` button.

Validates the multilingue pre-conditions for a micro-site slug and builds the
list of 7 ``CommandSpec`` items (4 ``/micro-sites-publish`` invocations
interleaved with 3 ``/clear``) ready to be emitted via
``signal_bus.pipeline_ready``.

Validation gates (any failure -> raise ``MicroSitesMultilingueError``):

1. ``deploy-map.json`` exists and maps the slug to a non-reserved entry.
2. ``locales-map.json`` exists and parses; declares the 4 canonical countries
   (``br``, ``it``, ``es``, ``us``).
3. For each of the 4 locales (``pt-BR``, ``it-IT``, ``es-ES``, ``en-US``):
   ``sites/<slug>/messages/<locale>/site.json`` exists and is non-empty.
4. For each of the 4 locales: ``REVIEW.md`` exists and the YAML-ish front
   matter declares ``status: approved``.

Decoupled from PySide6 so it can be unit-tested headless. The widget handler
catches ``MicroSitesMultilingueError`` and routes it to a red toast.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from workflow_app.domain import (
    CommandSpec,
    EffortLevel,
    InteractionType,
    ModelName,
)

CANONICAL_COUNTRIES: tuple[str, ...] = ("br", "it", "es", "us")
COUNTRY_TO_LOCALE: dict[str, str] = {
    "br": "pt-BR",
    "it": "it-IT",
    "es": "es-ES",
    "us": "en-US",
}
WORKSPACE_REL = Path("output/workspace/micro-sites")


class MicroSitesMultilingueError(Exception):
    """Validation failed before enqueue. The message goes straight to a toast."""


@dataclass(frozen=True)
class MultilingueBuildResult:
    """Output of ``validate_and_build_specs``."""

    slug: str
    host: str
    specs: list[CommandSpec] = field(default_factory=list)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MicroSitesMultilingueError(
            f"arquivo nao encontrado: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise MicroSitesMultilingueError(
            f"JSON invalido em {path}: {exc.msg}"
        ) from exc


def _resolve_host(deploy_map: dict, slug: str) -> str:
    targets = deploy_map.get("targets")
    if not isinstance(targets, list):
        raise MicroSitesMultilingueError(
            "deploy-map.json sem campo 'targets' (lista)"
        )
    for entry in targets:
        if not isinstance(entry, dict):
            continue
        if entry.get("slug") != slug:
            continue
        if entry.get("reserved"):
            raise MicroSitesMultilingueError(
                f"slug '{slug}' esta marcado como reserved=true em deploy-map.json"
            )
        branch = entry.get("branch")
        if not isinstance(branch, str) or not branch.strip():
            raise MicroSitesMultilingueError(
                f"slug '{slug}' sem 'branch' em deploy-map.json"
            )
        return f"{branch}.hostingersite.com"
    raise MicroSitesMultilingueError(
        f"slug '{slug}' nao encontrado em deploy-map.json"
    )


def _validate_locales_map(locales_map: dict) -> None:
    countries = locales_map.get("countries")
    if not isinstance(countries, dict):
        raise MicroSitesMultilingueError(
            "locales-map.json sem campo 'countries' (objeto)"
        )
    missing = [c for c in CANONICAL_COUNTRIES if c not in countries]
    if missing:
        raise MicroSitesMultilingueError(
            f"locales-map.json nao declara os paises: {', '.join(missing)}"
        )
    for country in CANONICAL_COUNTRIES:
        entry = countries[country]
        if not isinstance(entry, dict):
            raise MicroSitesMultilingueError(
                f"locales-map.json countries.{country} nao e objeto"
            )
        expected_locale = COUNTRY_TO_LOCALE[country]
        actual_locale = entry.get("locale")
        if actual_locale != expected_locale:
            raise MicroSitesMultilingueError(
                f"locales-map.json countries.{country}.locale esperado "
                f"'{expected_locale}', encontrou '{actual_locale}'"
            )


def _validate_messages(site_dir: Path, slug: str) -> None:
    for locale in COUNTRY_TO_LOCALE.values():
        locale_dir = site_dir / "messages" / locale
        site_json = locale_dir / "site.json"
        if not site_json.is_file() or site_json.stat().st_size == 0:
            raise MicroSitesMultilingueError(
                f"sites/{slug}/messages/{locale}/site.json ausente ou vazio"
            )
        review_md = locale_dir / "REVIEW.md"
        if not review_md.is_file():
            raise MicroSitesMultilingueError(
                f"sites/{slug}/messages/{locale}/REVIEW.md ausente"
            )
        if not _review_is_approved(review_md):
            raise MicroSitesMultilingueError(
                f"sites/{slug}/messages/{locale}/REVIEW.md sem 'status: approved'"
            )


def _review_is_approved(review_md: Path) -> bool:
    """Read YAML-ish front matter and check ``status: approved`` literally."""
    text = review_md.read_text(encoding="utf-8")
    # Parse only the first front matter block (between leading --- and next ---).
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end < 0:
        return False
    block = text[3:end]
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if line.startswith("status:"):
            value = line.split(":", 1)[1].strip().strip('"').strip("'")
            return value == "approved"
    return False


def _build_specs(host: str) -> list[CommandSpec]:
    """Construct the canonical ``CommandSpec`` sequence br/it/es/us.

    Order:
      /clear /model opus /effort high  -> publish-br
      /clear                           -> publish-it
      /clear                           -> publish-es
      /clear                           -> publish-us

    Regras (ai-forge/rules/workflow-app-command-lists.md): o PRIMEIRO grupo
    recebe /clear /model opus /effort high para estabelecer estado conhecido na
    partida (secao 3.4). As 4 invocacoes rodam todas em opus/high, entao os
    grupos seguintes emitem APENAS /clear — /model e /effort suprimidos por
    anti-redundancia (secao 3.1). Sem /clear final (autocast cuida da cauda).
    """
    specs: list[CommandSpec] = []
    pos = 0
    for idx, country in enumerate(CANONICAL_COUNTRIES):
        if idx == 0:
            # secao 3.4: primeiro grupo recebe o triplet completo.
            for name in ("/clear", "/model opus", "/effort high"):
                pos += 1
                specs.append(
                    CommandSpec(
                        name=name,
                        model=ModelName.OPUS,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=pos,
                    )
                )
        else:
            # secao 3.1: model/effort inalterados (opus/high) -> apenas /clear.
            pos += 1
            specs.append(
                CommandSpec(
                    name="/clear",
                    model=ModelName.OPUS,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    position=pos,
                )
            )
        pos += 1
        specs.append(
            CommandSpec(
                name=f"/micro-sites-publish {host} --country {country}",
                model=ModelName.OPUS,
                effort=EffortLevel.HIGH,
                interaction_type=InteractionType.AUTO,
                config_path="",
                position=pos,
            )
        )
    return specs


def validate_and_build_specs(
    slug: str,
    repo_root: Path,
) -> MultilingueBuildResult:
    """Run all 4 validation gates and return host + specs on success.

    ``repo_root`` is the SystemForge repo root (parent of
    ``output/workspace/micro-sites``). Tests inject a tmp_path here; the widget
    handler uses ``Path.cwd()`` (the workflow-app is launched from repo root).
    """
    slug = slug.strip()
    if not slug:
        raise MicroSitesMultilingueError("slug vazio")

    workspace = repo_root / WORKSPACE_REL
    if not workspace.is_dir():
        raise MicroSitesMultilingueError(
            f"workspace ausente: {workspace} (esperado output/workspace/micro-sites/)"
        )

    deploy_map = _read_json(workspace / "config" / "deploy-map.json")
    host = _resolve_host(deploy_map, slug)

    locales_map = _read_json(workspace / "config" / "locales-map.json")
    _validate_locales_map(locales_map)

    site_dir = workspace / "sites" / slug
    if not site_dir.is_dir():
        raise MicroSitesMultilingueError(
            f"sites/{slug}/ nao existe em {workspace}"
        )
    _validate_messages(site_dir, slug)

    return MultilingueBuildResult(
        slug=slug,
        host=host,
        specs=_build_specs(host),
    )


__all__: Sequence[str] = (
    "CANONICAL_COUNTRIES",
    "COUNTRY_TO_LOCALE",
    "MicroSitesMultilingueError",
    "MultilingueBuildResult",
    "validate_and_build_specs",
)
