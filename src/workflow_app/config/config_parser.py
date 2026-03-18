"""
config_parser — Parse e detecção automática de project.json do SystemForge.

Suporta os 3 formatos do pipeline:
  - V3: tem "basic_flow" com sub-chaves de paths
  - V2: tem "docs_root", "wbs_root", etc. direto no root
  - V1: tem "output_root" como string (legacy)

Funções principais:
  parse_config(path)   → PipelineConfig
  detect_config(cwd)   → str | None
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from workflow_app.errors import ConfigError


@dataclass
class PipelineConfig:
    """Configuração extraída de um project.json do SystemForge.

    Todos os paths são strings conforme registradas no arquivo JSON
    (relativas ao project root — não são resolvidas aqui).
    """

    config_path: str               # path absoluto do arquivo lido
    project_name: str              # campo "name" do JSON
    brief_root: str                # onde ficam INTAKE.md, etc.
    docs_root: str                 # onde ficam PRD.md, HLD.md, etc.
    wbs_root: str                  # onde ficam os modules/TASKs
    workspace_root: str            # root do código gerado
    language: str = "pt-BR"        # idioma da interface do projeto
    raw: dict = field(default_factory=dict, repr=False)  # JSON original completo

    @property
    def project_dir(self) -> Path:
        """Diretório raiz do projeto (onde está o .claude/).

        Funciona tanto para .claude/project.json quanto para
        .claude/projects/*.json — busca o ancestral chamado '.claude'
        e retorna o seu pai.
        """
        for parent in Path(self.config_path).parents:
            if parent.name == ".claude":
                return parent.parent
        return Path(self.config_path).parent.parent


def parse_config(path: str) -> PipelineConfig:
    """Lê e parseia um project.json do SystemForge.

    Suporta V3 (basic_flow), V2 (campos diretos) e V1 (output_root).

    Args:
        path: path absoluto ou relativo para o arquivo .json.

    Returns:
        PipelineConfig com todos os campos preenchidos.

    Raises:
        FileNotFoundError: se o arquivo não existe.
        ConfigError: se o JSON é inválido ou campos obrigatórios estão ausentes.
    """
    resolved = Path(path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Config não encontrado: {resolved}")

    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"JSON inválido em {resolved}: {exc}", cause=exc
        ) from exc

    project_name = raw.get("name", resolved.stem)

    # ── Detecta versão e extrai paths ──────────────────────────────────────
    if "basic_flow" in raw:
        # V3
        bf = raw["basic_flow"]
        brief_root = bf.get("brief_root", "")
        docs_root = bf.get("docs_root", "")
        wbs_root = bf.get("wbs_root", "")
        workspace_root = bf.get("workspace_root", "")
    elif "docs_root" in raw or "wbs_root" in raw:
        # V2 — campos direto no root
        brief_root = raw.get("brief_root", raw.get("docs_root", ""))
        docs_root = raw.get("docs_root", "")
        wbs_root = raw.get("wbs_root", "")
        workspace_root = raw.get("workspace_root", raw.get("output_root", ""))
    elif "output_root" in raw:
        # V1 — apenas output_root como string
        output_root = str(raw["output_root"])
        brief_root = f"{output_root}/brief"
        docs_root = f"{output_root}/docs"
        wbs_root = f"{output_root}/wbs"
        workspace_root = f"{output_root}/workspace"
    else:
        raise ConfigError(
            f"Formato de project.json não reconhecido em {resolved}. "
            "Campos esperados: 'basic_flow' (V3), 'docs_root' (V2) ou 'output_root' (V1)."
        )

    if not docs_root:
        raise ConfigError(
            f"Campo 'docs_root' ausente ou vazio em {resolved}."
        )

    # Extrai idioma do project_details se disponível
    language = "pt-BR"
    pd = raw.get("project_details", {})
    lang_map = pd.get("language", {})
    if lang_map:
        for lang_key, enabled in lang_map.items():
            if enabled:
                language = lang_key
                break

    return PipelineConfig(
        config_path=str(resolved),
        project_name=project_name,
        brief_root=brief_root,
        docs_root=docs_root,
        wbs_root=wbs_root,
        workspace_root=workspace_root,
        language=language,
        raw=raw,
    )


def detect_config(cwd: str | None = None) -> str | None:
    """Detecta automaticamente um project.json a partir do diretório corrente.

    Estratégia:
    1. Glob ``**/.claude/project.json`` a partir de cwd (max 5 níveis)
    2. Fallback: glob ``**/.claude/projects/*.json``
    3. Se nenhum encontrado: retorna None

    Args:
        cwd: diretório de busca. Se None, usa os.getcwd().

    Returns:
        Path absoluto do primeiro arquivo encontrado, ou None.
    """
    search_root = Path(cwd).resolve() if cwd else Path.cwd()

    # Estratégia 1: project.json canônico
    primary = _glob_max_depth(search_root, ".claude/project.json", max_depth=5)
    if primary:
        return str(primary[0])

    # Estratégia 2: qualquer .json em .claude/projects/
    secondary = _glob_max_depth(search_root, ".claude/projects/*.json", max_depth=5)
    if secondary:
        # Prefere arquivos que não sejam project-2.json (showroom)
        non_showroom = [
            p for p in secondary
            if "project-2" not in p.name and "showroom" not in str(p)
        ]
        if non_showroom:
            return str(non_showroom[0])
        return str(secondary[0])

    return None


def _glob_max_depth(root: Path, pattern: str, max_depth: int) -> list[Path]:
    """Glob com profundidade máxima para evitar varreduras excessivas."""
    results: list[Path] = []
    for depth in range(0, max_depth + 1):
        prefix = "/".join(["*"] * depth)
        full_pattern = f"{prefix}/{pattern}" if depth > 0 else pattern
        matched = sorted(root.glob(full_pattern))
        results.extend(matched)
        if results:
            break
    return results
