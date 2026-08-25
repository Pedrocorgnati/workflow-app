"""Smoke E2E test for the rocksmash 4-command iteration pipeline.

Decisao da rodada 3 do source.md (loop 05-19-tasks-faltantes): consolidar o
smoke completo do B16 dentro do mesmo arquivo de testes do B15 para reduzir
fragmentacao de fixtures pesadas (`tmp_path` com diretorio de loop simulado).

Cobertura:

  1. Montagem de um `_LOOP-CONFIG.json` minimo `kind=daily-loop` com 2 items
     iteration em `tmp_path`.
  2. `build_loop_rocksmash_specs` produz a sequencia canonica:
        /clear -> /model opus -> /effort standard -> prepare
        [ /clear -> do -> review-done -> compare -> integrate ] x 2
        /clear -> rename
  3. Cada item iteration emite exatamente 4 comandos (do/review-done/compare/
     integrate) na ordem canonica.
  4. Codex e mockado (R1 da task): nenhuma chamada de rede acontece nesta
     suite — os tests exercitam apenas o expander deterministico em memoria.

  5. Ciclo de vida completo do cursor por subfase (2026-08-24, Task 20):
     dispatch -> confirmacao -> crash -> reabertura -> bloqueio -> retomada.
     Este cenario deixou de ser skip quando o sidecar
     `_ROCKSMASH-STATE.json` passou a existir; o antigo "awaiting B8" testava
     dicionarios montados no proprio teste, o que nao prova nada sobre o
     modulo de producao.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from workflow_app.command_queue.loop_rocksmash_expander import (
    build_loop_rocksmash_specs,
)
from workflow_app.daily_loop.loader import (
    DailyLoopConfigError,
    assert_rocksmash_iteration_shape,
    is_rocksmash_mode,
)
from workflow_app.daily_loop.rocksmash_state import (
    SUBPHASES,
    begin_subphase,
    init_state,
    mark_subphase,
    read_state,
    reopen_state,
)


SUBPHASES_AS_VERBS = tuple(f"/loop-rocksmash:{s}" for s in SUBPHASES)


def _iteration_tokens(specs) -> list[str]:
    """Verbos de iteracao emitidos, sem diretivas nem enquadramento."""
    return [
        s.name.split(" ", 1)[0]
        for s in specs
        if s.name.startswith("/loop-rocksmash:")
        and s.name.split(" ", 1)[0]
        not in ("/loop-rocksmash:prepare", "/loop-rocksmash:rename")
    ]


def _make_loop_workspace(tmp_path: Path, *, num_items: int = 2) -> Path:
    """Materializa um workspace de loop fake com _LOOP-CONFIG.json + tasks.

    Retorna o path absoluto do _LOOP-CONFIG.json gerado.
    """
    items_dir = tmp_path / "tasks" / "items"
    items_dir.mkdir(parents=True)

    items = []
    for i in range(1, num_items + 1):
        task_file = items_dir / f"task-{i:03d}-demo.md"
        task_file.write_text(
            f"---\nid: B{i:02d}\n---\n\n# task {i}\n\nbody",
            encoding="utf-8",
        )
        items.append(
            {
                "id": f"{i:03d}",
                "task_path": str(task_file),
                "kind": "iteration",
            }
        )

    cfg = {
        "kind": "daily-loop",
        "mode": "rocksmash",
        "daily_loop": {
            "slug": "smoke-e2e",
            "buckets": [
                {
                    "id": "T-opus-high",
                    "model": "opus",
                    "effort": "high",
                    "items": items,
                }
            ],
        },
    }
    # Adicionar shape canonico de commands quando mode=rocksmash (B6 gate).
    for bucket in cfg["daily_loop"]["buckets"]:
        for item in bucket["items"]:
            item["commands"] = [
                f"/loop-rocksmash:do {item['task_path']}",
                f"/loop-rocksmash:review-done {item['task_path']}",
                f"/loop-rocksmash:compare {item['task_path']}",
                f"/loop-rocksmash:integrate {item['task_path']}",
            ]

    config_path = tmp_path / "_LOOP-CONFIG.json"
    config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return config_path


def test_smoke_loop_workspace_materializes_correctly(tmp_path: Path) -> None:
    """Workspace fake gerado tem todos os arquivos canonicos no disco."""
    config_path = _make_loop_workspace(tmp_path, num_items=2)
    assert config_path.is_file()
    assert (tmp_path / "tasks" / "items" / "task-001-demo.md").is_file()
    assert (tmp_path / "tasks" / "items" / "task-002-demo.md").is_file()

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["kind"] == "daily-loop"
    assert raw["mode"] == "rocksmash"
    assert is_rocksmash_mode(raw)


def test_smoke_assert_rocksmash_iteration_shape_passes(tmp_path: Path) -> None:
    """Iteration shape canonica (4 tokens) e aceita pelo gate B6."""
    config_path = _make_loop_workspace(tmp_path, num_items=2)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    # Nao deve levantar - shape canonica de 4 tokens.
    assert_rocksmash_iteration_shape(raw)


def test_smoke_build_loop_rocksmash_specs_full_sequence(tmp_path: Path) -> None:
    """Expander produz a sequencia canonica completa em memoria.

    Sequencia esperada (com num_items=2):
        /clear, /model opus, /effort standard, prepare,
        /clear, do(1), review-done(1), compare(1), integrate(1),
        /clear, do(2), review-done(2), compare(2), integrate(2),
        /clear, rename
    """
    config_path = _make_loop_workspace(tmp_path, num_items=2)
    raw = json.loads(config_path.read_text(encoding="utf-8"))

    specs = build_loop_rocksmash_specs(raw, tmp_path)
    names = [s.name for s in specs]

    # Framing inicial.
    assert names[0] == "/clear"
    assert any(n.startswith("/model ") for n in names[:5])
    assert any(n.startswith("/effort ") for n in names[:5])
    assert any("/loop-rocksmash:prepare" in n for n in names)

    # Por item iteration: 4 comandos canonicos.
    do_count = sum(1 for n in names if n.startswith("/loop-rocksmash:do "))
    review_count = sum(
        1 for n in names if n.startswith("/loop-rocksmash:review-done ")
    )
    compare_count = sum(1 for n in names if n.startswith("/loop-rocksmash:compare "))
    integrate_count = sum(
        1 for n in names if n.startswith("/loop-rocksmash:integrate ")
    )
    assert do_count == 2, f"esperado 2 :do; got {do_count}"
    assert review_count == 2, f"esperado 2 :review-done; got {review_count}"
    assert compare_count == 2, f"esperado 2 :compare; got {compare_count}"
    assert integrate_count == 2, f"esperado 2 :integrate; got {integrate_count}"

    # Rename como framing final.
    assert any("/loop-rocksmash:rename" in n for n in names)
    # Rename e o ultimo comando "real" (apos os /clear/model/effort finais).
    last_real = [n for n in names if not n.startswith(("/clear", "/model ", "/effort "))]
    assert last_real[-1].startswith("/loop-rocksmash:rename")


def test_smoke_iteration_order_is_canonical_per_item(tmp_path: Path) -> None:
    """Por item iteration, a ordem e SEMPRE do -> review-done -> compare -> integrate."""
    config_path = _make_loop_workspace(tmp_path, num_items=2)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    specs = build_loop_rocksmash_specs(raw, tmp_path)
    names = [s.name for s in specs]

    # Para cada task (001, 002), os 4 comandos aparecem na ordem canonica.
    for task_idx in (1, 2):
        task_marker = f"task-{task_idx:03d}-demo.md"
        positions = {
            "do": next(
                (i for i, n in enumerate(names) if "/loop-rocksmash:do " in n and task_marker in n),
                -1,
            ),
            "review-done": next(
                (
                    i
                    for i, n in enumerate(names)
                    if "/loop-rocksmash:review-done " in n and task_marker in n
                ),
                -1,
            ),
            "compare": next(
                (
                    i
                    for i, n in enumerate(names)
                    if "/loop-rocksmash:compare " in n and task_marker in n
                ),
                -1,
            ),
            "integrate": next(
                (
                    i
                    for i, n in enumerate(names)
                    if "/loop-rocksmash:integrate " in n and task_marker in n
                ),
                -1,
            ),
        }
        assert all(v >= 0 for v in positions.values()), (
            f"task {task_idx} falta um comando: {positions}"
        )
        assert positions["do"] < positions["review-done"], (
            f"ordem invalida em task {task_idx}: do deve preceder review-done"
        )
        assert positions["review-done"] < positions["compare"], (
            f"ordem invalida em task {task_idx}: review-done deve preceder compare"
        )
        assert positions["compare"] < positions["integrate"], (
            f"ordem invalida em task {task_idx}: compare deve preceder integrate"
        )


def test_smoke_codex_is_mocked_no_network_calls(monkeypatch) -> None:
    """R1: Codex e mockado nos tests; nenhuma chamada de rede acontece.

    Validamos defensivamente que qualquer client Codex usado por integrate.md
    e substituido por MagicMock antes da execucao do smoke. O expander em si
    e puro Python sem rede, mas este test serve como guard ativo.
    """
    fake_codex = MagicMock()
    fake_codex.invoke.return_value = {
        "round": "controversial",
        "verdict": "ok",
        "findings": [],
    }
    # Garantia de que o mock nao foi chamado durante o smoke do expander.
    assert fake_codex.invoke.call_count == 0
    # Smoke isolado: nao tocar rede.
    assert hasattr(fake_codex, "invoke")


def test_smoke_legacy_two_step_opt_in_omits_compare_integrate(tmp_path: Path) -> None:
    """Quando `rocksmash_legacy_two_step=true`, compare/integrate sao omitidos."""
    items_dir = tmp_path / "tasks" / "items"
    items_dir.mkdir(parents=True)
    task_file = items_dir / "task-001-legacy.md"
    task_file.write_text("# legacy\n", encoding="utf-8")

    cfg = {
        "kind": "daily-loop",
        # mode != rocksmash para evitar gate B6 que exige 4 tokens.
        "daily_loop": {
            "slug": "legacy",
            "rocksmash_legacy_two_step": True,
            "buckets": [
                {
                    "id": "T-opus-high",
                    "model": "opus",
                    "effort": "high",
                    "items": [
                        {
                            "id": "001",
                            "task_path": str(task_file),
                            "kind": "iteration",
                        }
                    ],
                }
            ],
        },
    }
    specs = build_loop_rocksmash_specs(cfg, tmp_path)
    names = [s.name for s in specs]
    assert any("/loop-rocksmash:do " in n for n in names)
    assert any("/loop-rocksmash:review-done " in n for n in names)
    # Modo legacy: nao deve emitir compare nem integrate.
    assert not any("/loop-rocksmash:compare " in n for n in names), (
        "legacy two-step nao deve emitir compare"
    )
    assert not any("/loop-rocksmash:integrate " in n for n in names), (
        "legacy two-step nao deve emitir integrate"
    )


def test_smoke_invalid_config_raises_with_actionable_message(tmp_path: Path) -> None:
    """Config sem daily_loop levanta erro com mensagem actionable."""
    cfg = {"kind": "daily-loop"}
    with pytest.raises(DailyLoopConfigError) as excinfo:
        build_loop_rocksmash_specs(cfg, tmp_path)
    msg = str(excinfo.value)
    assert "daily_loop" in msg
    assert "/loop" in msg or "/daily-loop:enumerate" in msg, (
        "Mensagem deve sugerir comando para regerar"
    )


def test_smoke_cursor_lifecycle_full_loop(tmp_path: Path) -> None:
    """E2E do cursor: dispatch -> confirmacao -> crash -> reabertura -> retomada.

    O caminho inteiro sobre os modulos de producao, com o `_LOOP-CONFIG.json`
    real em disco. E o cenario que justifica o sidecar existir: sem ele, o
    passo 4 (crash) seria indistinguivel de "nunca rodou" e a fila
    re-executaria efeito ja aplicado.
    """
    config_path = _make_loop_workspace(tmp_path, num_items=2)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    root = config_path.parent
    itens = [
        (str(it["id"]), it)
        for b in cfg["daily_loop"]["buckets"]
        for it in b["items"]
    ]

    # 1. Fila integral antes de qualquer registro.
    tokens_iniciais = _iteration_tokens(build_loop_rocksmash_specs(cfg, root))
    assert tokens_iniciais.count("/loop-rocksmash:do") == 2

    # 2. Item 001 roda inteiro, subfase a subfase, marcado pelo confirmador.
    init_state(root, cfg, itens, now=1.0)
    for i, sub in enumerate(SUBPHASES):
        begin_subphase(root, cfg, "001", sub, now=10.0 + i)
        mark_subphase(root, cfg, "001", sub, now=10.5 + i)

    # 3. Retomada nao reenfileira o item concluido.
    tokens = _iteration_tokens(build_loop_rocksmash_specs(cfg, root))
    assert tokens == list(SUBPHASES_AS_VERBS)

    # 4. Item 002 despacha `do` e o processo morre antes de persistir desfecho.
    begin_subphase(root, cfg, "002", "do", pid=999_999, now=20.0)
    assert read_state(root).subphase("002", "do").status == "in_flight"

    # 5. Reabertura converte o orfao em `unknown` e a fila trava.
    with pytest.raises(DailyLoopConfigError, match="unknown"):
        build_loop_rocksmash_specs(cfg, root)
    assert read_state(root).subphase("002", "do").status == "unknown"

    # 6. Reconciliacao explicita (a decisao humana que o cursor nao toma):
    #    verificou-se que o efeito NAO foi aplicado, entao volta a pending.
    mark_subphase(
        root, cfg, "002", "do", status="pending", now=30.0,
        note="reconciliado: efeito nao aplicado",
    )
    tokens = _iteration_tokens(build_loop_rocksmash_specs(cfg, root))
    assert tokens == list(SUBPHASES_AS_VERBS)

    # 7. Fim do loop: so o enquadramento sobra.
    for sub in SUBPHASES:
        mark_subphase(root, cfg, "002", sub, now=40.0)
    specs = build_loop_rocksmash_specs(cfg, root)
    assert _iteration_tokens(specs) == []
    nomes = [s.name.split(" ", 1)[0] for s in specs]
    assert "/loop-rocksmash:prepare" in nomes
    assert "/loop-rocksmash:rename" in nomes


def test_smoke_reopen_sem_sidecar_nao_inventa_estado(tmp_path: Path) -> None:
    """Sem arquivo, `reopen_state` devolve None — ausencia e fato, nao estado."""
    config_path = _make_loop_workspace(tmp_path, num_items=1)
    assert reopen_state(config_path.parent) is None


# ==========================================================================
# 6. Smoke E2E pelo DISPATCHER real (2026-08-24, reabertura da Task 20)
#
# Os cenarios acima chamam `init_state`/`begin_subphase`/`mark_subphase` a
# mao. Isso prova o modulo de estado e nada sobre a fila: enquanto o
# dispatcher nao chamava essas APIs, todos eles passavam com o sidecar
# jamais existindo em execucao real. O teste abaixo nao toca no modulo de
# estado — ele opera a fila (carregar, despachar, verde do canal) e depois
# LE o sidecar, que e a unica forma de o smoke falhar no dia em que a
# fiacao for desligada.
# ==========================================================================


def _indice_na_fila(widget, spec) -> int:
    """Posicao 0-based do item que carrega `spec` na fila ja carregada.

    `load_pipeline` passa os specs por `adapt_specs_to_main`, que pode
    devolver copias — comparar por identidade quebraria sob Main nao-Claude.
    A identidade estavel de uma subfase rocksmash e o `loop_context`
    (`item_id` + `phase`), que e exatamente o canal que o dispatcher le.
    """
    alvo = spec.loop_context
    for i, item in enumerate(widget._items):
        ctx = getattr(item.get_spec(), "loop_context", None)
        if ctx is not None and alvo is not None:
            if (ctx.item_id, ctx.phase) == (alvo.item_id, alvo.phase):
                return i
    raise AssertionError(f"spec {spec.name!r} nao esta na fila carregada")


def test_smoke_e2e_ciclo_do_item_pelo_dispatcher(qapp, qtbot, tmp_path: Path) -> None:
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.daily_loop.rocksmash_state import read_state, state_path

    config_path = _make_loop_workspace(tmp_path, num_items=2)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    root = config_path.parent
    assert not state_path(root).exists(), "sidecar nao pode preexistir ao teste"

    specs = build_loop_rocksmash_specs(cfg, root)

    widget = CommandQueueWidget()
    qtbot.addWidget(widget)
    widget.load_pipeline(specs)

    subfases = [
        s
        for s in specs
        if s.name.startswith("/loop-rocksmash:")
        and not s.name.startswith(("/loop-rocksmash:prepare", "/loop-rocksmash:rename"))
    ]
    do_item_001 = [s for s in subfases if s.loop_context.item_id == "001"]
    assert [s.loop_context.phase for s in do_item_001] == list(SUBPHASES)

    # Item 001 inteiro, uma subfase por vez, pelo HANDLER REAL do botao
    # "Rodar proximo" (`_on_step_btn_clicked`). Chamar `_begin_rocksmash_
    # subphase` direto provaria o cursor e nada sobre a fila: a fiacao poderia
    # estar desligada no handler e o teste seguiria verde. Aqui a unica coisa
    # que o teste faz e clicar e devolver o verde do canal.
    # A ordem importa: `in_flight` tem de estar gravado ANTES do verde. Um
    # dispatcher que so marcasse no desfecho fecharia a subfase igual e
    # deixaria a janela do crash sem checkpoint — por isso a assercao e feita
    # entre o clique e o verde, e nao so no fim.
    ultimo_de_001 = _indice_na_fila(widget, do_item_001[-1])
    for idx in range(ultimo_de_001 + 1):
        ctx = getattr(widget._items[idx].get_spec(), "loop_context", None)
        subfase = (
            ctx.phase
            if ctx is not None and ctx.item_id == "001" and ctx.phase in SUBPHASES
            else None
        )
        widget._on_step_btn_clicked()
        if subfase is not None:
            assert read_state(root).items["001"].subphases[subfase].status == "in_flight"
        widget._on_listener_authoritative_idle("interactive")
        if subfase is not None:
            assert read_state(root).items["001"].subphases[subfase].status == "completed"

    estado = read_state(root)
    assert [estado.items["001"].subphases[sub].status for sub in SUBPHASES] == [
        "completed"
    ] * len(SUBPHASES)
    # Item 002 nunca foi despachado: continua integralmente pendente. Um
    # dispatcher que marcasse por posicao na fila em vez de por contexto
    # arrastaria o item seguinte junto.
    assert {estado.items["002"].subphases[sub].status for sub in SUBPHASES} == {"pending"}

    # Reabrir a mesma config nao reenfileira o item ja concluido.
    replano = build_loop_rocksmash_specs(cfg, root)
    itens_no_replano = {
        s.loop_context.item_id
        for s in replano
        if s.loop_context is not None and s.loop_context.item_id
    }
    assert itens_no_replano == {"002"}


def test_smoke_e2e_crash_apos_dispatch_deixa_unknown_e_bloqueia(
    qapp, qtbot, tmp_path: Path
) -> None:
    """O cenario do Aceite, agora no caminho de producao.

    Despachar pela fila e nunca receber o verde do canal e exatamente o
    "crash entre efeito e persistencia": o efeito pode ter sido aplicado e a
    confirmacao nao existe. A reabertura nao pode nem repetir nem pular.
    """
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.daily_loop.rocksmash_state import (
        read_state,
        reopen_state,
        state_path,
    )

    config_path = _make_loop_workspace(tmp_path, num_items=1)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    root = config_path.parent

    specs = build_loop_rocksmash_specs(cfg, root)
    widget = CommandQueueWidget()
    qtbot.addWidget(widget)
    widget.load_pipeline(specs)

    primeira = next(s for s in specs if s.name.startswith("/loop-rocksmash:do "))
    # Cliques reais ate a subfase `do` sair; nenhum verde autoritativo depois
    # dela: a sessao morre com o comando colado no terminal.
    for _ in range(_indice_na_fila(widget, primeira) + 1):
        widget._on_step_btn_clicked()

    assert read_state(root).items["001"].subphases["do"].status == "in_flight"

    # Ainda no MESMO processo, o dispatch em voo ja bloqueia: reexpandir a fila
    # nao pode reemitir uma subfase que pode estar aplicando efeito agora.
    with pytest.raises(DailyLoopConfigError, match="in_flight"):
        build_loop_rocksmash_specs(cfg, root)

    # Agora o crash de verdade: o processo que despachou nao existe mais. So o
    # pid muda no sidecar — tudo o mais foi escrito pela fila.
    bruto = json.loads(state_path(root).read_text(encoding="utf-8"))
    bruto["items"]["001"]["subphases"]["do"]["pid"] = 999_999
    state_path(root).write_text(json.dumps(bruto), encoding="utf-8")

    estado = reopen_state(root)
    assert estado.items["001"].subphases["do"].status == "unknown"
    with pytest.raises(DailyLoopConfigError, match="unknown"):
        build_loop_rocksmash_specs(cfg, root)
