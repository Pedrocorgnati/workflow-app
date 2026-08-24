"""Testes do sidecar `_ROCKSMASH-STATE.json` (Task 19).

O que estes testes travam nao e a serializacao — e a politica. O sidecar existe
porque, antes dele, "onde a fila parou" so era legivel por um humano lendo
Markdown. Se qualquer das regras abaixo afrouxar, o sidecar volta a ser mais uma
opiniao sobre progresso em vez da autoridade:

- vale so para a config que o gerou (`config_hash`);
- quem executa nao confirma (`actor == "queue-confirmer"`);
- escrita atomica, sem residuo temporario;
- `failed` nao vira pendencia silenciosa (isso e de `loop-failed-reconciliation.md`);
- ausencia de arquivo e fato; arquivo ilegivel e erro, nunca "nada rodou".

Regras: `ai-forge/rules/rocksmash.md` secao 2.4 (R15..R19).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflow_app.daily_loop.rocksmash_state import (
    QUEUE_CONFIRMER,
    SCHEMA_VERSION,
    STATE_FILENAME,
    SUBPHASES,
    RocksmashStateError,
    compute_config_hash,
    init_state,
    mark_subphase,
    read_state,
    state_path,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _config(n: int = 2) -> dict:
    return {
        "schema_version": "3.0.0",
        "daily_loop": {
            "buckets": [
                {
                    "model": "opus",
                    "effort": "high",
                    "items": [
                        {"id": f"{i:03d}", "task_path": f"tasks/task-{i}.md"}
                        for i in range(1, n + 1)
                    ],
                }
            ]
        },
    }


def _iteration_items(n: int = 2) -> list[tuple[str, dict]]:
    return [(f"{i:03d}", {"task_path": f"tasks/task-{i}.md"}) for i in range(1, n + 1)]


# --------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------


def test_schema_e_json_valido_e_declara_a_versao_do_modulo() -> None:
    schema_path = (
        _repo_root()
        / "ai-forge/workflow-app/src/workflow_app/daily_loop/rocksmash_state.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    obrigatorios = set(schema["required"])
    assert {"schema_version", "loop_slug", "config_hash", "items"} <= obrigatorios

    item = schema["properties"]["items"]["additionalProperties"]
    subfases = item["properties"]["subphases"]
    # As quatro subfases sao estrutura, nao convencao: um consumidor que so
    # encontra `do` nao consegue distinguir "nao rodou" de "schema antigo".
    assert set(subfases["properties"]) == set(SUBPHASES)
    assert set(subfases["required"]) == set(SUBPHASES)


def test_arquivo_gravado_casa_com_o_shape_do_schema(tmp_path: Path) -> None:
    init_state(tmp_path, _config(), _iteration_items(), now=1.0)
    data = json.loads(state_path(tmp_path).read_text(encoding="utf-8"))

    assert data["schema_version"] == SCHEMA_VERSION
    assert len(data["config_hash"]) == 64
    assert set(data["items"]) == {"001", "002"}
    assert set(data["items"]["001"]["subphases"]) == set(SUBPHASES)
    # `null` = nao observado (R19): recem-criado nao afirma que nada aconteceu,
    # afirma que nada foi observado.
    assert data["items"]["001"]["subphases"]["do"]["completed_at"] is None
    assert data["items"]["001"]["subphases"]["do"]["actor"] is None


def test_schema_version_divergente_e_recusado(tmp_path: Path) -> None:
    init_state(tmp_path, _config(), _iteration_items(), now=1.0)
    alvo = state_path(tmp_path)
    data = json.loads(alvo.read_text(encoding="utf-8"))
    data["schema_version"] = "0.9.0"
    alvo.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RocksmashStateError, match="schema_version"):
        read_state(tmp_path)


# --------------------------------------------------------------------------
# config_hash (R16)
# --------------------------------------------------------------------------


def test_hash_e_estavel_sob_reordenacao_de_chaves() -> None:
    a = {"z": 1, "a": {"y": 2, "b": 3}}
    b = {"a": {"b": 3, "y": 2}, "z": 1}
    assert compute_config_hash(a) == compute_config_hash(b)


def test_hash_muda_quando_o_conteudo_muda() -> None:
    assert compute_config_hash(_config(2)) != compute_config_hash(_config(3))


def test_init_recusa_estado_stale_e_nao_apaga_progresso(tmp_path: Path) -> None:
    cfg = _config(2)
    init_state(tmp_path, cfg, _iteration_items(2), now=1.0)
    mark_subphase(tmp_path, cfg, "001", "do", now=2.0)

    outra = _config(3)
    with pytest.raises(RocksmashStateError, match="stale"):
        init_state(tmp_path, outra, _iteration_items(3), now=3.0)

    # O progresso da config anterior continua em disco: descartar e decisao do
    # operador, nao efeito colateral de um init.
    assert read_state(tmp_path).is_completed("001", "do")


def test_init_com_overwrite_stale_reinicializa(tmp_path: Path) -> None:
    cfg = _config(2)
    init_state(tmp_path, cfg, _iteration_items(2), now=1.0)
    mark_subphase(tmp_path, cfg, "001", "do", now=2.0)

    outra = _config(3)
    novo = init_state(
        tmp_path, outra, _iteration_items(3), now=3.0, overwrite_stale=True
    )
    assert novo.config_hash == compute_config_hash(outra)
    assert not novo.is_completed("001", "do")


def test_mark_subphase_recusa_estado_stale(tmp_path: Path) -> None:
    init_state(tmp_path, _config(2), _iteration_items(2), now=1.0)
    with pytest.raises(RocksmashStateError, match="stale"):
        mark_subphase(tmp_path, _config(3), "001", "do", now=2.0)


def test_init_e_idempotente_para_a_mesma_config(tmp_path: Path) -> None:
    cfg = _config()
    init_state(tmp_path, cfg, _iteration_items(), now=1.0)
    mark_subphase(tmp_path, cfg, "001", "do", now=2.0)

    devolvido = init_state(tmp_path, cfg, _iteration_items(), now=3.0)
    assert devolvido.is_completed("001", "do")
    assert devolvido.updated_at == 2.0


# --------------------------------------------------------------------------
# actor (R17)
# --------------------------------------------------------------------------


def test_apenas_o_confirmador_da_fila_escreve(tmp_path: Path) -> None:
    cfg = _config()
    init_state(tmp_path, cfg, _iteration_items(), now=1.0)

    for impostor in ("/loop-rocksmash:do", "claude", "llm", "operator"):
        with pytest.raises(RocksmashStateError, match="Escritor unico"):
            mark_subphase(tmp_path, cfg, "001", "do", actor=impostor, now=2.0)

    estado = mark_subphase(tmp_path, cfg, "001", "do", actor=QUEUE_CONFIRMER, now=2.0)
    assert estado.subphase("001", "do").actor == QUEUE_CONFIRMER


def test_status_fora_do_enum_e_recusado(tmp_path: Path) -> None:
    cfg = _config()
    init_state(tmp_path, cfg, _iteration_items(), now=1.0)
    with pytest.raises(RocksmashStateError, match="status invalido"):
        mark_subphase(tmp_path, cfg, "001", "do", status="quase", now=2.0)


def test_subfase_desconhecida_e_recusada(tmp_path: Path) -> None:
    cfg = _config()
    init_state(tmp_path, cfg, _iteration_items(), now=1.0)
    with pytest.raises(RocksmashStateError):
        mark_subphase(tmp_path, cfg, "001", "rename", now=2.0)


def test_item_desconhecido_e_recusado(tmp_path: Path) -> None:
    cfg = _config()
    init_state(tmp_path, cfg, _iteration_items(), now=1.0)
    with pytest.raises(RocksmashStateError):
        mark_subphase(tmp_path, cfg, "999", "do", now=2.0)


# --------------------------------------------------------------------------
# io (R18) e leitura
# --------------------------------------------------------------------------


def test_escrita_nao_deixa_residuo_temporario(tmp_path: Path) -> None:
    cfg = _config()
    init_state(tmp_path, cfg, _iteration_items(), now=1.0)
    mark_subphase(tmp_path, cfg, "001", "do", now=2.0)

    nomes = {p.name for p in tmp_path.iterdir()}
    assert STATE_FILENAME in nomes
    assert not [n for n in nomes if n.endswith(".tmp") or n.startswith("tmp")]


def test_ausencia_e_fato_mas_corrupcao_e_erro(tmp_path: Path) -> None:
    # Ausencia: nao ha estado, e isso e informacao util (loop nunca iniciado).
    assert read_state(tmp_path) is None

    # Corrupcao: devolver None aqui reportaria "nada rodou" para um loop que
    # pode ter rodado inteiro. Falhar alto e a unica resposta honesta.
    state_path(tmp_path).write_text("{nao json", encoding="utf-8")
    with pytest.raises(RocksmashStateError):
        read_state(tmp_path)


# --------------------------------------------------------------------------
# cursor
# --------------------------------------------------------------------------


def test_pending_segue_a_ordem_canonica_das_subfases(tmp_path: Path) -> None:
    cfg = _config(1)
    init_state(tmp_path, cfg, _iteration_items(1), now=1.0)
    estado = read_state(tmp_path)
    assert estado.pending_subphases() == [("001", sp) for sp in SUBPHASES]

    estado = mark_subphase(tmp_path, cfg, "001", "do", now=2.0)
    assert estado.pending_subphases() == [("001", sp) for sp in SUBPHASES[1:]]


def test_failed_nao_e_pendencia_e_defere_a_reconciliacao(tmp_path: Path) -> None:
    cfg = _config(1)
    init_state(tmp_path, cfg, _iteration_items(1), now=1.0)
    estado = mark_subphase(tmp_path, cfg, "001", "do", status="failed", now=2.0)

    # Retomar automaticamente um `failed` seria inventar politica de retry aqui;
    # ela vive em ai-forge/rules/loop-failed-reconciliation.md.
    assert ("001", "do") not in estado.pending_subphases()
    assert estado.pending_subphases() == [("001", sp) for sp in SUBPHASES[1:]]


def test_regras_declaram_o_sidecar_como_autoridade_unica() -> None:
    texto = (_repo_root() / "ai-forge/rules/rocksmash.md").read_text(encoding="utf-8")
    assert "_ROCKSMASH-STATE.json" in texto
    assert "unica autoridade de maquina" in texto
    # As projecoes precisam estar nomeadas: uma regra que diz "o resto e
    # projecao" sem dizer qual resto nao impede ninguem de ler o Markdown.
    assert "rocksmash-progress.md" in texto
    assert QUEUE_CONFIRMER in texto
