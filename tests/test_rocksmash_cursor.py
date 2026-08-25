"""Cursor por subfase do rocksmash (Task 20).

Este arquivo substitui o placeholder de 2026-05-19, que testava dicionarios
montados dentro do proprio teste e pulava tudo que dependia do modulo real.
Um teste que simula o estado localmente prova apenas que o autor do teste sabe
escrever JSON; ele passa igual se o cursor de producao nunca for escrito.

Aqui todo cenario passa pelo SUT: `build_resume_plan` e
`build_loop_rocksmash_specs` do expander, e o sidecar real de
`workflow_app.daily_loop.rocksmash_state`.

O que esta travado:

* retomada emite SO as subfases `pending`, na ordem canonica (12.2.13);
* item inteiro concluido nao volta para a fila (10.1.1);
* crash entre efeito e persistencia deixa `unknown` e bloqueia auto-retomada;
* `failed` bloqueia igual — a decisao e de reconciliacao, nao do cursor;
* default quadruplo preservado, modo legacy de dois passos ainda testado
  (12.2.14);
* config alterada (stale) nunca e consumida em silencio.

Adenda 2026-08-24 (fechamento do bloqueio de D2): ate aqui o arquivo provava o
PLANO de retomada e nada mais. O bloqueio da Task 20 era outro — o expander so
LIA o sidecar; ninguem o criava em execucao e nenhuma spec carregava a
identidade do item. As duas classes no fim do arquivo travam justamente isso:

* expandir cria o sidecar (`init_state` ganhou chamador em `src/`) sem alterar
  a fila desta expansao, e reexpandir preserva o progresso ja gravado;
* cada subfase viaja com `LoopExecutionContext` (item, subfase, bucket, modo),
  diretiva nenhuma recebe contexto, e o enquadramento correlaciona sem afirmar
  item.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from workflow_app.command_queue.loop_rocksmash_expander import (
    ROCKSMASH_CONTEXT_MODE,
    _ITERATION_VERBS_CANONICAL,
    _ITERATION_VERBS_LEGACY,
    build_loop_rocksmash_specs,
    build_resume_plan,
)
from workflow_app.command_queue.rocksmash_cursor import RocksmashRuntimeCursor
from workflow_app.daily_loop.loader import DailyLoopConfigError
from workflow_app.daily_loop.rocksmash_state import (
    SUBPHASES,
    SUBPHASES_LEGACY,
    begin_subphase,
    init_state,
    mark_subphase,
    read_state,
    reopen_state,
    state_path,
)


# --------------------------------------------------------------------------
# fixtures locais (config real, lida pelo expander real)
# --------------------------------------------------------------------------


def _config(n: int = 3, *, legacy_two_step: bool = False) -> dict:
    daily_loop: dict = {
        "buckets": [
            {
                "id": "T-opus-high",
                "model": "opus",
                "effort": "high",
                "items": [
                    {
                        "id": f"{i:03d}",
                        "kind": "iteration",
                        "task_path": f"tasks/items/task-{i:03d}.md",
                    }
                    for i in range(1, n + 1)
                ],
            }
        ]
    }
    if legacy_two_step:
        daily_loop["rocksmash_legacy_two_step"] = True
    return {"kind": "daily-loop", "schema_version": "3.0.0", "daily_loop": daily_loop}


def _loop(tmp_path: Path, cfg: dict) -> Path:
    (tmp_path / "_LOOP-CONFIG.json").write_text(
        json.dumps(cfg, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


def _iteration_items(cfg: dict) -> list[tuple[str, dict]]:
    return [
        (str(it["id"]), it)
        for b in cfg["daily_loop"]["buckets"]
        for it in b["items"]
    ]


def _tokens(specs) -> list[str]:
    return [
        s.name.split(" ", 1)[0]
        for s in specs
        if not (s.name == "/clear" or s.name.startswith(("/model ", "/effort ")))
    ]


# --------------------------------------------------------------------------
# plano de retomada (SUT: build_resume_plan)
# --------------------------------------------------------------------------


def test_sem_estado_o_plano_e_integral() -> None:
    plano = build_resume_plan(None, ["001", "002"], SUBPHASES)
    assert plano == [("001", SUBPHASES), ("002", SUBPHASES)]


def test_plano_emite_so_as_subfases_pending_na_ordem_canonica(tmp_path: Path) -> None:
    cfg = _config(2)
    root = _loop(tmp_path, cfg)
    init_state(root, cfg, _iteration_items(cfg), now=1.0)
    mark_subphase(root, cfg, "001", "do", now=2.0)
    mark_subphase(root, cfg, "001", "review-done", now=3.0)

    plano = build_resume_plan(read_state(root), ["001", "002"], SUBPHASES)
    assert plano == [("001", ("compare", "integrate")), ("002", SUBPHASES)]


def test_item_totalmente_concluido_some_do_plano(tmp_path: Path) -> None:
    cfg = _config(2)
    root = _loop(tmp_path, cfg)
    init_state(root, cfg, _iteration_items(cfg), now=1.0)
    for sub in SUBPHASES:
        mark_subphase(root, cfg, "001", sub, now=2.0)

    plano = build_resume_plan(read_state(root), ["001", "002"], SUBPHASES)
    assert [iid for iid, _ in plano] == ["002"]


def test_item_ausente_do_estado_roda_bloco_inteiro(tmp_path: Path) -> None:
    cfg = _config(1)
    root = _loop(tmp_path, cfg)
    init_state(root, cfg, _iteration_items(cfg), now=1.0)

    # "002" existe na config mas nao foi registrado: nada observado sobre ele.
    plano = build_resume_plan(read_state(root), ["001", "002"], SUBPHASES)
    assert ("002", SUBPHASES) in plano


# --------------------------------------------------------------------------
# bloqueio: failed / unknown / in_flight
# --------------------------------------------------------------------------


def test_failed_bloqueia_a_retomada_automatica(tmp_path: Path) -> None:
    cfg = _config(1)
    root = _loop(tmp_path, cfg)
    init_state(root, cfg, _iteration_items(cfg), now=1.0)
    mark_subphase(root, cfg, "001", "do", status="failed", now=2.0)

    with pytest.raises(DailyLoopConfigError, match="001/do=failed"):
        build_resume_plan(read_state(root), ["001"], SUBPHASES)


def test_crash_entre_efeito_e_persistencia_vira_unknown_e_bloqueia(
    tmp_path: Path,
) -> None:
    """O cenario que o cursor existe para cobrir.

    `begin_subphase` marca `in_flight` ANTES do dispatch; o processo morre sem
    escrever o desfecho. Na reabertura, o pid nao existe mais: a subfase vira
    `unknown` — nao `pending` (autorizaria re-executar efeito ja aplicado) e
    nao `completed` (inventaria conclusao).
    """
    cfg = _config(1)
    root = _loop(tmp_path, cfg)
    init_state(root, cfg, _iteration_items(cfg), now=1.0)

    # pid inexistente = o processo que despachou morreu.
    begin_subphase(root, cfg, "001", "do", pid=999_999, now=2.0)
    assert read_state(root).subphase("001", "do").status == "in_flight"

    estado = reopen_state(root, now=3.0)
    assert estado.subphase("001", "do").status == "unknown"

    with pytest.raises(DailyLoopConfigError, match="001/do=unknown"):
        build_resume_plan(estado, ["001"], SUBPHASES)


def test_in_flight_com_processo_vivo_e_preservado_e_bloqueia(tmp_path: Path) -> None:
    cfg = _config(1)
    root = _loop(tmp_path, cfg)
    init_state(root, cfg, _iteration_items(cfg), now=1.0)
    begin_subphase(root, cfg, "001", "do", pid=os.getpid(), now=2.0)

    # Execucao viva nao e orfa: reabrir nao pode rebaixar para unknown.
    estado = reopen_state(root, now=3.0)
    assert estado.subphase("001", "do").status == "in_flight"

    with pytest.raises(DailyLoopConfigError, match="in_flight"):
        build_resume_plan(estado, ["001"], SUBPHASES)


def test_dispatch_concorrente_da_mesma_subfase_e_recusado(tmp_path: Path) -> None:
    cfg = _config(1)
    root = _loop(tmp_path, cfg)
    init_state(root, cfg, _iteration_items(cfg), now=1.0)
    begin_subphase(root, cfg, "001", "do", pid=os.getpid(), now=2.0)

    with pytest.raises(Exception, match="in_flight"):
        begin_subphase(root, cfg, "001", "do", pid=os.getpid(), now=3.0)


def test_bloqueio_de_outro_item_nao_impede_plano_quando_fora_do_escopo(
    tmp_path: Path,
) -> None:
    cfg = _config(2)
    root = _loop(tmp_path, cfg)
    init_state(root, cfg, _iteration_items(cfg), now=1.0)
    mark_subphase(root, cfg, "002", "do", status="failed", now=2.0)

    # O bloqueio vale para os itens que serao enfileirados; um item fora do
    # escopo desta expansao nao sequestra a fila.
    plano = build_resume_plan(read_state(root), ["001"], SUBPHASES)
    assert plano == [("001", SUBPHASES)]


# --------------------------------------------------------------------------
# integracao: fila expandida (SUT: build_loop_rocksmash_specs)
# --------------------------------------------------------------------------


def test_fila_integral_quando_nao_ha_sidecar(tmp_path: Path) -> None:
    cfg = _config(2)
    root = _loop(tmp_path, cfg)
    specs = build_loop_rocksmash_specs(cfg, root)

    assert _tokens(specs) == (
        ["/loop-rocksmash:prepare"]
        + list(_ITERATION_VERBS_CANONICAL) * 2
        + ["/loop-rocksmash:rename"]
    )


def test_reabrir_nao_reenfileira_iteracao_ja_processada(tmp_path: Path) -> None:
    cfg = _config(2)
    root = _loop(tmp_path, cfg)
    init_state(root, cfg, _iteration_items(cfg), now=1.0)
    for sub in SUBPHASES:
        mark_subphase(root, cfg, "001", sub, now=2.0)
    mark_subphase(root, cfg, "002", "do", now=3.0)

    specs = build_loop_rocksmash_specs(cfg, root)
    tokens = _tokens(specs)

    assert tokens == [
        "/loop-rocksmash:prepare",
        "/loop-rocksmash:review-done",
        "/loop-rocksmash:compare",
        "/loop-rocksmash:integrate",
        "/loop-rocksmash:rename",
    ]
    # Nenhum comando carrega o path do item ja concluido.
    assert not [s for s in specs if "task-001.md" in s.name]


def test_fila_bloqueada_quando_ha_unknown(tmp_path: Path) -> None:
    cfg = _config(1)
    root = _loop(tmp_path, cfg)
    init_state(root, cfg, _iteration_items(cfg), now=1.0)
    begin_subphase(root, cfg, "001", "do", pid=999_999, now=2.0)

    with pytest.raises(DailyLoopConfigError, match="unknown"):
        build_loop_rocksmash_specs(cfg, root)


def test_use_cursor_false_ignora_o_sidecar(tmp_path: Path) -> None:
    cfg = _config(1)
    root = _loop(tmp_path, cfg)
    init_state(root, cfg, _iteration_items(cfg), now=1.0)
    for sub in SUBPHASES:
        mark_subphase(root, cfg, "001", sub, now=2.0)

    specs = build_loop_rocksmash_specs(cfg, root, use_cursor=False)
    assert _tokens(specs) == (
        ["/loop-rocksmash:prepare"]
        + list(_ITERATION_VERBS_CANONICAL)
        + ["/loop-rocksmash:rename"]
    )


def test_sidecar_stale_nao_e_consumido_em_silencio(tmp_path: Path) -> None:
    cfg = _config(2)
    root = _loop(tmp_path, cfg)
    init_state(root, cfg, _iteration_items(cfg), now=1.0)

    # Config mudou (equivalente a um /loop-rocksmash:rename): os item_ids
    # podem ter mudado de significado.
    outra = _config(3)
    with pytest.raises(DailyLoopConfigError, match="stale"):
        build_loop_rocksmash_specs(outra, root)


def test_tudo_concluido_deixa_apenas_o_enquadramento(tmp_path: Path) -> None:
    cfg = _config(1)
    root = _loop(tmp_path, cfg)
    init_state(root, cfg, _iteration_items(cfg), now=1.0)
    for sub in SUBPHASES:
        mark_subphase(root, cfg, "001", sub, now=2.0)

    tokens = _tokens(build_loop_rocksmash_specs(cfg, root))
    assert tokens == ["/loop-rocksmash:prepare", "/loop-rocksmash:rename"]


# --------------------------------------------------------------------------
# default quadruplo e legacy (12.2.14)
# --------------------------------------------------------------------------


def test_default_continua_quadruplo() -> None:
    assert SUBPHASES == ("do", "review-done", "compare", "integrate")
    assert _ITERATION_VERBS_CANONICAL == tuple(
        f"/loop-rocksmash:{s}" for s in SUBPHASES
    )


def test_modo_legacy_de_dois_passos_continua_testado(tmp_path: Path) -> None:
    cfg = _config(2, legacy_two_step=True)
    root = _loop(tmp_path, cfg)
    init_state(
        root, cfg, _iteration_items(cfg), legacy_two_step=True, now=1.0
    )
    mark_subphase(root, cfg, "001", "do", now=2.0)

    specs = build_loop_rocksmash_specs(cfg, root)
    assert _tokens(specs) == [
        "/loop-rocksmash:prepare",
        "/loop-rocksmash:review-done",
        *list(_ITERATION_VERBS_LEGACY),
        "/loop-rocksmash:rename",
    ]
    # O sidecar legacy nao inventa compare/integrate.
    assert set(read_state(root).items["001"].subphases) == set(SUBPHASES_LEGACY)


# --------------------------------------------------------------------------
# persistencia
# --------------------------------------------------------------------------


def test_marcar_subfase_persiste_no_disco_e_sobrevive_ao_processo(
    tmp_path: Path,
) -> None:
    cfg = _config(1)
    root = _loop(tmp_path, cfg)
    init_state(root, cfg, _iteration_items(cfg), now=1.0)
    mark_subphase(root, cfg, "001", "do", now=2.0)

    em_disco = json.loads(state_path(root).read_text(encoding="utf-8"))
    assert em_disco["items"]["001"]["subphases"]["do"]["status"] == "completed"
    assert em_disco["items"]["001"]["subphases"]["review-done"]["status"] == "pending"


# --------------------------------------------------------------------------
# o sidecar nasce em execucao (SUT: build_loop_rocksmash_specs)
#
# `init_state` existia desde 2026-05-19 sem UM chamador em `src/`: o cursor era
# uma API que so testes exercitavam. Enquanto isso for verdade, marcar subfase
# em producao e impossivel — nao ha estado onde marcar.
# --------------------------------------------------------------------------


def _loop_dir(tmp_path: Path, cfg: dict, nome: str) -> Path:
    """Como `_loop`, mas em subpasta — para dois loops no mesmo `tmp_path`."""
    root = tmp_path / nome
    root.mkdir(parents=True, exist_ok=True)
    (root / "_LOOP-CONFIG.json").write_text(
        json.dumps(cfg, ensure_ascii=False), encoding="utf-8"
    )
    return root


def _subfase_specs(specs) -> list:
    return [
        s
        for s in specs
        if s.name.startswith("/loop-rocksmash:")
        and not s.name.startswith(("/loop-rocksmash:prepare", "/loop-rocksmash:rename"))
    ]


def test_expandir_cria_o_sidecar(tmp_path: Path) -> None:
    cfg = _config(2)
    root = _loop(tmp_path, cfg)
    assert not state_path(root).exists()

    build_loop_rocksmash_specs(cfg, root)

    estado = read_state(root)
    assert estado is not None
    assert sorted(estado.items) == ["001", "002"]
    assert all(
        sub.status == "pending"
        for item in estado.items.values()
        for sub in item.subphases.values()
    )


def test_criar_o_sidecar_nao_muda_a_fila_desta_expansao(tmp_path: Path) -> None:
    """Estado recem-criado e todo `pending`: o plano segue integral.

    Sem isto, ligar o cursor teria mudado a fila de quem nunca pediu retomada.
    """
    cfg = _config(2)
    com = _loop_dir(tmp_path, cfg, "com")
    sem = _loop_dir(tmp_path, cfg, "sem")

    assert _tokens(build_loop_rocksmash_specs(cfg, com)) == _tokens(
        build_loop_rocksmash_specs(cfg, sem, use_cursor=False)
    )


def test_use_cursor_false_nao_escreve_nada(tmp_path: Path) -> None:
    cfg = _config(1)
    root = _loop(tmp_path, cfg)
    build_loop_rocksmash_specs(cfg, root, use_cursor=False)
    assert not state_path(root).exists()


def test_expandir_duas_vezes_preserva_progresso(tmp_path: Path) -> None:
    """`init_state` e idempotente: reexpandir nao zera o que ja rodou."""
    cfg = _config(2)
    root = _loop(tmp_path, cfg)
    specs = build_loop_rocksmash_specs(cfg, root)
    cursor = RocksmashRuntimeCursor.from_specs(specs)
    assert cursor is not None
    ctx = _subfase_specs(specs)[0].loop_context
    cursor.begin(ctx)
    cursor.finish(ctx, failed=False)

    build_loop_rocksmash_specs(cfg, root)

    estado = read_state(root)
    assert estado.items["001"].subphases["do"].status == "completed"


# --------------------------------------------------------------------------
# identidade do item viaja pelo contexto, nunca pelo texto do comando
# --------------------------------------------------------------------------


def test_subfases_carregam_item_e_subfase(tmp_path: Path) -> None:
    cfg = _config(2)
    root = _loop(tmp_path, cfg)
    specs = build_loop_rocksmash_specs(cfg, root)

    pares = [(s.loop_context.item_id, s.loop_context.phase) for s in _subfase_specs(specs)]
    assert pares == [(iid, sub) for iid in ("001", "002") for sub in SUBPHASES]
    assert all(
        s.loop_context.mode == ROCKSMASH_CONTEXT_MODE for s in _subfase_specs(specs)
    )
    assert all(
        s.loop_context.bucket_id == "T-opus-high" for s in _subfase_specs(specs)
    )


def test_diretiva_nao_carrega_contexto(tmp_path: Path) -> None:
    """`/clear` nao pertence a item nenhum.

    Dar contexto a diretiva criaria correlacao falsa, que e pior que correlacao
    ausente: o desfecho do `/clear` seria contado como desfecho do item.
    """
    cfg = _config(1)
    root = _loop(tmp_path, cfg)
    specs = build_loop_rocksmash_specs(cfg, root)

    diretivas = [s for s in specs if s.name == "/clear" or s.name.startswith(("/model ", "/effort "))]
    assert diretivas
    assert all(s.loop_context is None for s in diretivas)


def test_framing_correlaciona_sem_afirmar_item(tmp_path: Path) -> None:
    cfg = _config(1)
    root = _loop(tmp_path, cfg)
    specs = build_loop_rocksmash_specs(cfg, root)

    framing = [
        s
        for s in specs
        if s.name.startswith(("/loop-rocksmash:prepare", "/loop-rocksmash:rename"))
    ]
    assert len(framing) == 2
    for s in framing:
        assert s.loop_context is not None
        assert s.loop_context.item_id is None
        assert not s.loop_context.is_item_scoped()


def test_queue_id_e_unico_por_expansao(tmp_path: Path) -> None:
    """Duas expansoes do mesmo loop sao duas execucoes distintas."""
    cfg = _config(1)
    root = _loop(tmp_path, cfg)
    a = build_loop_rocksmash_specs(cfg, root)
    b = build_loop_rocksmash_specs(cfg, root)

    assert (
        _subfase_specs(a)[0].loop_context.queue_id
        != _subfase_specs(b)[0].loop_context.queue_id
    )


def test_queue_id_e_o_mesmo_dentro_de_uma_expansao(tmp_path: Path) -> None:
    cfg = _config(2)
    root = _loop(tmp_path, cfg)
    specs = build_loop_rocksmash_specs(cfg, root)

    ids = {s.loop_context.queue_id for s in specs if s.loop_context is not None}
    assert len(ids) == 1
