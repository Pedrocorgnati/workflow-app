"""Tests for ``micro_sites_multilingue_expander`` (task-011).

Covers the 4 validation gates and the canonical 7-item spec ordering
emitted by the ``queue-btn-publish-micro-sites-multilingue`` button.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflow_app.command_queue.micro_sites_multilingue_expander import (
    CANONICAL_COUNTRIES,
    COUNTRY_TO_LOCALE,
    MicroSitesMultilingueError,
    validate_and_build_specs,
)
from workflow_app.domain import EffortLevel, ModelName

APPROVED_REVIEW = (
    "---\n"
    "slug: {slug}\n"
    "country: {country}\n"
    "locale: {locale}\n"
    "status: approved\n"
    "---\n"
    "ok\n"
)
PENDING_REVIEW = (
    "---\n"
    "slug: {slug}\n"
    "country: {country}\n"
    "locale: {locale}\n"
    "status: pending\n"
    "---\n"
)


def _seed_workspace(
    tmp_path: Path,
    slug: str = "a01",
    *,
    reserved: bool = False,
    drop_country: str | None = None,
    drop_locale_dir: str | None = None,
    drop_site_json: str | None = None,
    review_status_overrides: dict[str, str] | None = None,
) -> Path:
    """Build a minimal ``output/workspace/micro-sites/`` tree under ``tmp_path``.

    Returns the ``tmp_path`` (treated as repo_root by the expander).
    """
    workspace = tmp_path / "output" / "workspace" / "micro-sites"
    config = workspace / "config"
    config.mkdir(parents=True)

    targets = [
        {"slug": slug, "branch": "deploy-99", "reserved": reserved},
        {"slug": "other", "branch": "deploy-50", "reserved": False},
    ]
    (config / "deploy-map.json").write_text(
        json.dumps({"version": "1", "targets": targets})
    )

    countries: dict[str, dict] = {}
    for c in CANONICAL_COUNTRIES:
        if c == drop_country:
            continue
        countries[c] = {"locale": COUNTRY_TO_LOCALE[c]}
    (config / "locales-map.json").write_text(
        json.dumps({"version": "1.0.0", "default": "br", "countries": countries})
    )

    site_dir = workspace / "sites" / slug
    overrides = review_status_overrides or {}
    for country, locale in COUNTRY_TO_LOCALE.items():
        if drop_locale_dir == locale:
            continue
        locale_dir = site_dir / "messages" / locale
        locale_dir.mkdir(parents=True)
        if drop_site_json != locale:
            (locale_dir / "site.json").write_text(json.dumps({"slug": slug}))
        else:
            (locale_dir / "site.json").write_text("")
        status = overrides.get(locale, "approved")
        body = (APPROVED_REVIEW if status == "approved" else PENDING_REVIEW)
        (locale_dir / "REVIEW.md").write_text(
            body.format(slug=slug, country=country, locale=locale)
        )

    return tmp_path


class TestHappyPath:
    def test_returns_host_and_ten_specs(self, tmp_path):
        repo = _seed_workspace(tmp_path)
        result = validate_and_build_specs("a01", repo)
        assert result.host == "deploy-99.hostingersite.com"
        # 4 publish + 4 /clear + /model opus + /effort high = 10 (secao 3.4 prep).
        assert len(result.specs) == 10

    def test_canonical_order_br_it_es_us(self, tmp_path):
        repo = _seed_workspace(tmp_path)
        result = validate_and_build_specs("a01", repo)
        names = [s.name for s in result.specs]
        # Primeiro grupo recebe /clear /model opus /effort high (secao 3.4);
        # grupos seguintes so /clear (anti-redundancia secao 3.1).
        assert names == [
            "/clear",
            "/model opus",
            "/effort high",
            "/micro-sites-publish deploy-99.hostingersite.com --country br",
            "/clear",
            "/micro-sites-publish deploy-99.hostingersite.com --country it",
            "/clear",
            "/micro-sites-publish deploy-99.hostingersite.com --country es",
            "/clear",
            "/micro-sites-publish deploy-99.hostingersite.com --country us",
        ]

    def test_no_redundant_model_effort_directives(self, tmp_path):
        repo = _seed_workspace(tmp_path)
        names = [s.name for s in validate_and_build_specs("a01", repo).specs]
        # secao 3.1: /model e /effort emitidos exatamente UMA vez.
        assert sum(1 for n in names if n.startswith("/model ")) == 1
        assert sum(1 for n in names if n.startswith("/effort ")) == 1

    def test_no_trailing_clear(self, tmp_path):
        repo = _seed_workspace(tmp_path)
        result = validate_and_build_specs("a01", repo)
        assert result.specs[-1].name.startswith("/micro-sites-publish ")
        assert result.specs[-1].name.endswith("--country us")

    def test_publish_specs_use_opus_high(self, tmp_path):
        repo = _seed_workspace(tmp_path)
        result = validate_and_build_specs("a01", repo)
        publish_specs = [s for s in result.specs if s.name.startswith("/micro-sites-publish ")]
        assert len(publish_specs) == 4
        for s in publish_specs:
            assert s.model == ModelName.OPUS
            assert s.effort == EffortLevel.HIGH


class TestDeployMapGate:
    def test_slug_missing_raises(self, tmp_path):
        repo = _seed_workspace(tmp_path)
        with pytest.raises(MicroSitesMultilingueError, match="nao encontrado"):
            validate_and_build_specs("zzz-not-here", repo)

    def test_reserved_slug_raises(self, tmp_path):
        repo = _seed_workspace(tmp_path, reserved=True)
        with pytest.raises(MicroSitesMultilingueError, match="reserved"):
            validate_and_build_specs("a01", repo)

    def test_empty_slug_raises(self, tmp_path):
        repo = _seed_workspace(tmp_path)
        with pytest.raises(MicroSitesMultilingueError, match="vazio"):
            validate_and_build_specs("   ", repo)

    def test_missing_workspace_raises(self, tmp_path):
        with pytest.raises(MicroSitesMultilingueError, match="workspace ausente"):
            validate_and_build_specs("a01", tmp_path)


class TestLocalesMapGate:
    def test_missing_country_in_locales_map_raises(self, tmp_path):
        repo = _seed_workspace(tmp_path, drop_country="es")
        with pytest.raises(MicroSitesMultilingueError, match="nao declara os paises"):
            validate_and_build_specs("a01", repo)


class TestMessagesGate:
    def test_missing_locale_dir_raises(self, tmp_path):
        repo = _seed_workspace(tmp_path, drop_locale_dir="it-IT")
        with pytest.raises(MicroSitesMultilingueError, match="it-IT/site.json"):
            validate_and_build_specs("a01", repo)

    def test_empty_site_json_raises(self, tmp_path):
        repo = _seed_workspace(tmp_path, drop_site_json="en-US")
        with pytest.raises(MicroSitesMultilingueError, match="en-US/site.json"):
            validate_and_build_specs("a01", repo)


class TestReviewGate:
    def test_pending_status_blocks(self, tmp_path):
        repo = _seed_workspace(
            tmp_path,
            review_status_overrides={"pt-BR": "pending"},
        )
        with pytest.raises(MicroSitesMultilingueError, match="status: approved"):
            validate_and_build_specs("a01", repo)

    def test_all_four_must_be_approved(self, tmp_path):
        repo = _seed_workspace(
            tmp_path,
            review_status_overrides={"es-ES": "pending"},
        )
        with pytest.raises(MicroSitesMultilingueError, match="es-ES"):
            validate_and_build_specs("a01", repo)
