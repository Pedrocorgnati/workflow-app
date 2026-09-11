"""Testes de literais canonicos e template hardened (T5).

Cobre 4 cenarios do T5 (loop 05-21-implantation-tasklist-aba-brainstorm):
- test_action_literals_count_and_keys: literais canonicos (label -> texto), com
  a cardinalidade vindo de `_EXPECTED_KEYS` e nunca de um numero em prosa.
- test_hardened_template_renders_correctly: TEMPLATE_HARDENED com substituicao
  byte-a-byte dos 4 placeholders + clausula anti-injection.
- test_build_prompt_raises_for_invalid_action: ValueError em action fora
  do catalogo de `ACTION_LITERALS`.
- test_segunda_fase_saiu_e_as_chaves_viraram_inertes: Task 31 removeu o bloco
  de segunda fase; chaves agent2_*/action2 viraram inertes, nao um erro.

Hardening T9 §2: usa `importorskip` para evitar zona morta xfail enquanto
T5 nao entregar o modulo.
"""

from __future__ import annotations

import pytest

pytest.importorskip("workflow_app.widgets.mcp_prompt_actions")

pytestmark = pytest.mark.timeout(5)

from pathlib import Path

from tests._helpers import assert_deriva_a_tabela_sem_copiar
from workflow_app.widgets.mcp_prompt_actions import (
    ACTION_LITERALS,
    PROMPT_TEMPLATE_VERSION,
    TEMPLATE_HARDENED,
    TEMPLATE_SHORT,
    append_public_context,
    build_prompt,
    serialize_prompt_for_snapshot,
)

_EXPECTED_KEYS = frozenset(
    {
        "Otimizar",
        "Criar tasks",
        "Revisar tasks",
        "Revisar",
        "Executar",
        "Revisar execucao",
        "Criar arquivo",
        "Loop prepare",
        "Analisar complexidade",
        "Questionar",
        "Delegar",
        "Atualizar scaffolds e blueprints",
    }
)


def test_action_literals_count_and_keys():
    """ACTION_LITERALS expoe exatamente os labels canonicos (pt-BR).

    Cada literal e str nao-vazio e PROMPT_TEMPLATE_VERSION e versao
    semantic (date-based) usada para invalidar snapshots golden.
    """
    assert set(ACTION_LITERALS.keys()) == _EXPECTED_KEYS
    assert len(ACTION_LITERALS) == len(_EXPECTED_KEYS)
    for k, v in ACTION_LITERALS.items():
        assert isinstance(v, str) and v.strip(), f"{k}: literal vazio"
    assert isinstance(PROMPT_TEMPLATE_VERSION, str)
    assert PROMPT_TEMPLATE_VERSION


def test_hardened_template_renders_correctly(tmp_path):
    """build_prompt com target_path=True usa TEMPLATE_HARDENED.

    Validacoes:
    - Substituicao byte-a-byte de {target-path}, {agent-name}, {agent-path},
      {action}.
    - Bloco anti-injection ("INSTRUCOES DO SISTEMA" + clausula de
      precedencia) presente.
    - agent_path normalizado para POSIX (slash forward).
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    md_path = "blacksmith/brainstorm-mcp/seeds/01-criar-md.md"
    seed_meta = {
        "agent_name": "Estruturador",
        "agent_path": "ai-forge\\MCP\\agents\\criar-md.md",
        "action": "Otimizar",
        "target_path": True,
    }
    out = build_prompt(seed_meta, md_path, repo_root)
    assert "INSTRUCOES DO SISTEMA" in out
    assert "Estruturador" in out
    # POSIX normalization:
    assert "ai-forge/MCP/agents/criar-md.md" in out
    assert "\\" not in out
    # md_path injetado em {target-path}:
    assert md_path in out
    # Literal canonico (Otimizar) injetado:
    assert ACTION_LITERALS["Otimizar"] in out
    # Spot-check do template base:
    assert "{target-path}" not in out
    assert "{action}" not in out


def test_loop_prepare_action_declara_modo_e_destino_condicional(tmp_path):
    """Loop prepare explica o handoff sem executar /loop.

    Este teste ja afirmou `queue-btn-loop` como destino UNICO. Era falso: os
    cinco modos reais nao caem todos na mesma fila, e mandar um documento
    `--cmd-single` para `queue-btn-loop` poe o operador na fila errada. C6/Task
    21 tornou o destino condicional ao modo, e o teste passou a exigir os tres
    botoes reais em vez de um so.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    md_path = "blacksmith/brainstorm-mcp/06-03-plano.md"
    seed_meta = {
        "agent_name": "Preparador",
        "agent_path": "ai-forge/MCP/agents/loop-preparer-rules.md",
        "action": "Loop prepare",
        "target_path": True,
    }
    out = build_prompt(seed_meta, md_path, repo_root)
    assert "ai-forge/rules/loop-rules.md" in out
    # O prompt aponta a tabela e manda aplica-la ao modo escolhido. Ele NAO
    # repete os modos nem os botoes: essa copia e o que envelheceu antes
    # (dizia `queue-btn-loop` para os cinco) e o que `BRAINSTORM.md:21`
    # proibe. Quem julga a tabela e
    # `test_seed_body_invariants.test_a_persona_do_loop_carrega_a_tabela...`.
    assert_deriva_a_tabela_sem_copiar(out, "build_prompt('Loop prepare')")
    assert "sem executar /loop" in out
    # A proibicao universal continua nomeando o artefato.
    assert "_LOOP-CONFIG.json" in out
    assert "NAO cria" in out


def test_analisar_complexidade_routes_simples_or_loop(tmp_path):
    """Analise de complexidade aponta os dois canais e persiste o veredito."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    md_path = "blacksmith/brainstorm-mcp/06-23-ideia.md"
    seed_meta = {
        "agent_name": "roteador de complexidade SystemForge",
        "agent_path": "ai-forge/MCP/agents/complexity-router-rules.md",
        "action": "Analisar complexidade",
        "target_path": True,
    }
    out = build_prompt(seed_meta, md_path, repo_root)
    # Canal SIMPLES e canal LOOP citados por data-testid.
    assert 'data-testid="mcp-prompt-btn-criar-task"' in out
    # PR1(a): o canal LOOP e o BOTAO `mcp-prompt-btn-loop-prepare`. O sufixo
    # `-checkbox` e o testid do indicador visual gerado por `_InlineCheckBox`,
    # que NAO despacha nada; mandar o operador clicar nele era rota morta.
    assert 'data-testid="mcp-prompt-btn-loop-prepare"' in out
    assert "mcp-prompt-btn-loop-prepare-checkbox" not in out
    # C6/Task 22: o botao de fila DEPENDE do modo e nao e decidido aqui; o
    # roteador manda consultar a tabela unica em vez de presumir um nome.
    assert "nao presuma queue-btn-loop" in out
    assert "ai-forge/MCP/agents/loop-preparer-rules.md" in out
    # Veredito binario e bloco de saida ancorados.
    assert "SIMPLES ou LOOP" in out
    assert "## Veredito de roteamento" in out
    assert "ai-forge/MCP/agents/complexity-router-rules.md" in out
    # C6/Task 22: a action deixou de ser read-only. A escrita permitida e UMA
    # chave, e a proibicao do resto vem em linha propria.
    assert "brainstorm_complexity" in out
    assert "ai-forge/templates/mcp-flow/BRAINSTORM.md" in out
    assert (
        "PROIBIDO alterar qualquer coisa fora da chave `brainstorm_complexity`:"
        in out.splitlines()[-3]
    )
    assert "sem reescrever" not in out or "nao reescreva" in out


def test_build_prompt_raises_for_invalid_action(tmp_path):
    """Action fora de ACTION_LITERALS levanta ValueError byte-a-byte."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seed_meta = {
        "agent_name": "x",
        "agent_path": "agents/x.md",
        "action": "NaoExiste",
        "target_path": False,
    }
    with pytest.raises(ValueError, match="action invalida"):
        build_prompt(seed_meta, None, repo_root)


def test_segunda_fase_saiu_e_as_chaves_viraram_inertes(tmp_path):
    """Task 31: `agent2_*` + `action2` nao anexam mais nada -- e nao levantam.

    O teste que vivia aqui provava que o bloco de segunda fase era montado.
    Ele passava porque construia `seed_meta` A MAO com as tres chaves; em
    producao nenhum seed as declara e `MCPPromptButton.payload()` nunca as
    emite, entao o consumidor existia sem produtor (A5). Removida a segunda
    fase, o que interessa provar e o contrario: um caller externo que ainda
    monte essas chaves nao quebra -- elas passam a ser ignoradas.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    agent2 = repo_root / "agents" / "phase2.md"
    agent2.parent.mkdir(parents=True)
    agent2.write_text("# phase 2 rules\n", encoding="utf-8")
    seed_meta = {
        "agent_name": "Phase1Agent",
        "agent_path": "agents/phase1.md",
        "action": "Criar arquivo",
        "target_path": False,
        "agent2_name": "Phase2Agent",
        "agent2_path": "agents/phase2.md",
        "action2": "Loop prepare",
    }
    out = build_prompt(seed_meta, None, repo_root)

    assert "Phase1Agent" in out
    assert ACTION_LITERALS["Criar arquivo"] in out
    assert "Phase2Agent" not in out
    assert "segunda fase" not in out.lower()
    # Sanity: ambos templates importados (smoke do contrato do modulo).
    assert isinstance(TEMPLATE_HARDENED, str) and TEMPLATE_HARDENED
    assert isinstance(TEMPLATE_SHORT, str) and TEMPLATE_SHORT


def test_o_modulo_nao_tem_mais_produtor_nem_consumidor_de_segunda_fase():
    """Nenhum simbolo de segunda fase sobrevive como CODIGO (comentario vale).

    Verificado por AST, nao por grep de texto: o comentario que explica a
    remocao cita `agent2_path` de proposito, e um grep cru o acusaria.
    """
    import ast

    from workflow_app.widgets import mcp_prompt_actions

    arvore = ast.parse(
        Path(mcp_prompt_actions.__file__).read_text(encoding="utf-8")
    )
    nomes = {
        n.id for n in ast.walk(arvore) if isinstance(n, ast.Name)
    } | {
        n.name for n in ast.walk(arvore) if isinstance(n, ast.FunctionDef)
    }
    assert not any("AGENT2" in n or "second_phase" in n for n in nomes)

    literais = {
        n.value for n in ast.walk(arvore)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert not any(
        "agent2_" in s or "action2" in s for s in literais
    )


def test_build_prompt_appends_public_project_loop_context_snapshot(tmp_path):
    """Snapshot inline do contexto publico opcional project/loop."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seed_meta = {
        "agent_name": "Preparador",
        "agent_path": "agents/preparador.md",
        "action": "Otimizar",
        "target_path": True,
    }
    project = {
        "name": "workflow-app",
        "commercial_name": "Workflow App",
        "basic_flow": {
            "docs_root": "output/docs/workflow-app",
            "wbs_root": "output/wbs/workflow-app",
            "workspace_root": "ai-forge/workflow-app",
        },
        "project_type": {"feature": {"enabled": True}},
        "project_details": {
            "target_stack": {"backend": {"python": True}},
            "language": {"pt-BR": True},
        },
    }
    loop = {
        "name": "loop-prompt-context",
        "commercial_name": "Loop Prompt Context",
        "kind": "daily-loop",
        "mode": "task",
        "daily_loop": {
            "slug": "loop-prompt-context",
            "total_items": 8,
            "progress_path": "PROGRESS.md",
            "tasks_dir": "tasks",
        },
        "basic_flow": {
            "brief_root": "blacksmith/loop-archives/loop-prompt-context",
            "docs_root": "blacksmith/loop-archives/loop-prompt-context",
            "wbs_root": "blacksmith/loop-archives/loop-prompt-context",
            "workspace_root": ".",
        },
    }
    enriched = append_public_context(seed_meta, project=project, loop=loop)
    out = serialize_prompt_for_snapshot(
        build_prompt(enriched, "blacksmith/brainstorm-mcp/contexto.md", repo_root)
    )
    # v13 = Codex R3 s3: o literal `Loop prepare` parou de copiar enum de
    # modos, mapa de botoes e veredito de JSON por modo; passou a citar a
    # tabela `Handoff condicional por modo` da persona, dona unica deles.
    # v12 = Codex F9 #1: o literal `Loop prepare` deixou de afirmar que a
    # pipeline /loop produz o `_LOOP-CONFIG.json` nos CINCO modos.
    # v11 = C2c: o bloco `## Prompt canonico` do seed passou a vencer
    # `ACTION_LITERALS` na montagem do prompt (Task 26).
    assert PROMPT_TEMPLATE_VERSION == "2026-08-26-v14"
    assert "--- CONTEXTO PUBLICO OPCIONAL ---" in out
    assert '"project": {' in out
    assert '"loop": {' in out
    assert '"workspace_root": "ai-forge/workflow-app"' in out
    assert '"slug": "loop-prompt-context"' in out
    assert "credentials" not in out


def test_public_context_omits_blocked_names_and_token_like_values(tmp_path):
    """ST007: fixture artificial nao vaza nomes nem valores sensiveis."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seed_meta = {
        "agent_name": "Auditor",
        "agent_path": "agents/auditor.md",
        "action": "Otimizar",
        "target_path": False,
    }
    project = {
        "name": "safe-project",
        "commercial_name": "Safe Project",
        "credentials": {"api_key": "sk-test-123"},
        "basic_flow": {
            "docs_root": "docs",
            "wbs_root": "wbs",
            "workspace_root": "workspace",
            "fake_secret": "github_pat_abc",
        },
        "project_details": {
            "target_stack": {
                "backend": {"python": True},
                "internal_token": "ASIA123456789",
            },
            "language": {
                "pt-BR": True,
                "private": "-----BEGIN PRIVATE KEY-----",
            },
        },
    }
    loop = {
        "name": "safe-loop",
        "kind": "daily-loop",
        "daily_loop": {
            "slug": "safe-loop",
            "total_items": 1,
            "progress_path": "PROGRESS.md",
            "tasks_dir": "tasks",
        },
        "basic_flow": {
            "brief_root": "brief",
            "docs_root": "docs",
            "wbs_root": "wbs",
            "workspace_root": ".",
            "notes": {
                "part1": "sk-test-",
                "part2": "123",
            },
        },
    }
    enriched = append_public_context(seed_meta, project=project, loop=loop)
    out = serialize_prompt_for_snapshot(build_prompt(enriched, None, repo_root))

    blocked_fragments = [
        "credentials",
        "fake_secret",
        "internal_token",
        "api_key",
        "sk-test-123",
        "github_pat_abc",
        "ASIA123456789",
        "-----BEGIN PRIVATE KEY-----",
        "sk-test-",
        '"part2": "123"',
    ]
    for fragment in blocked_fragments:
        assert fragment not in out
    assert "safe-project" in out
    assert "safe-loop" in out


# ── Task 32: `.format()` nao volta ao caminho de montagem ────────────────────


def test_nenhum_format_no_caminho_de_montagem_do_prompt():
    """Verificado por AST, nao por grep -- e a diferenca importa.

    O docstring do modulo (`mcp_prompt_actions.py:20`) diz, em texto,
    "Substituicao via `.replace()` literal (NUNCA `.format()`)". Um
    `grep -F '.format('` acusa essa linha e volta vermelho com o modulo
    correto; um teste que aceita esse falso positivo e um teste que sera
    desligado no primeiro dia util. A AST enxerga so codigo: docstring,
    comentario e string literal nao viram `ast.Call`.

    O que a regra protege: `_fill_template` insere o corpo do seed no lugar
    de `{action}`. Com `.format()`, qualquer chave dentro desse corpo --
    `{slug}`, `{workspace_root}`, `{0}`, `{__class__}` -- seria reprocessada
    pelo interpolador, o que e injecao com o texto do proprio seed como
    vetor. Com `str.replace()` sequencial, o texto inserido chega literal.
    """
    import ast

    modulo = __import__(
        "workflow_app.widgets.mcp_prompt_actions", fromlist=["__file__"],
    )
    fonte = Path(modulo.__file__).read_text(encoding="utf-8")

    # A premissa do docstring desta funcao tem de continuar verdadeira: se a
    # mencao textual sumir, este teste vira um AST sem motivo declarado.
    assert ".format()" in fonte, (
        "o docstring que justifica a checagem por AST sumiu do modulo"
    )

    proibidos = {"format", "format_map"}
    achados = [
        f"linha {no.lineno}: .{no.func.attr}()"
        for no in ast.walk(ast.parse(fonte))
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Attribute)
        and no.func.attr in proibidos
    ]
    assert not achados, (
        "montagem de prompt voltou a interpolar via format: " + "; ".join(achados)
    )


def test_o_preenchimento_do_template_usa_replace():
    """O contra-teste do anterior: a AST prova a PRESENCA do mecanismo certo.

    Sem isto, apagar `_fill_template` inteira deixaria o teste de ausencia
    de `.format()` verde -- ausencia de tudo satisfaz ausencia de um.
    """
    import ast

    modulo = __import__(
        "workflow_app.widgets.mcp_prompt_actions", fromlist=["__file__"],
    )
    arvore = ast.parse(Path(modulo.__file__).read_text(encoding="utf-8"))
    (fill,) = [
        n for n in ast.walk(arvore)
        if isinstance(n, ast.FunctionDef) and n.name == "_fill_template"
    ]
    chamadas = {
        n.func.attr
        for n in ast.walk(fill)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "replace" in chamadas
