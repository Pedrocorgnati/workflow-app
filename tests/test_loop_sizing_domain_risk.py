"""Gate do eixo de RISCO DE DOMINIO do classificador do /loop (Task 11).

O PASSO 2 de `/loop:individual-analysis` mede ESFORCO. Ele nao mede
CONSEQUENCIA. O caso real `08-19` (conecta-clube, ondas 0-4) provou o
buraco: praticamente toda a lista caiu no piso da tabela de esforco e o
operador precisou sobrescrever a distribuicao inteira a mao por causa de
entitlement, LGPD, webhook de terceiro e revogacao de acesso.

O PASSO 2R fechou o buraco com um catalogo de sinais deterministico. A fonte
da verdade desse catalogo e o bloco ```json risk-signals``` dentro do proprio
`.claude/commands/loop/individual-analysis.md` - nao existe copia em outro
arquivo. Este teste LE aquele bloco, aplica a regra descrita ao lado dele e
trava o comportamento contra uma fixture derivada dos titulos reais do 08-19.

Editar o catalogo no markdown muda o que este teste verifica; e essa a
intencao. O que o teste nao deixa mudar em silencio e o contrato: os itens de
risco nao voltam para o piso e o detector de anomalia continua disparando na
assinatura do 08-19.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUTOR_SPEC = REPO_ROOT / ".claude" / "commands" / "loop" / "individual-analysis.md"
FIXTURE_08_19 = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "loop"
    / "titulos-risco-dominio-08-19.json"
)

# Ordem canonica de tiers. Risco so PROMOVE nesta escada; nunca rebaixa.
_TIER_ORDEM = [
    ("sonnet", "standard"),
    ("sonnet", "high"),
    ("opus", "standard"),
    ("opus", "high"),
]


# --------------------------------------------------------------------------
# Leitura do catalogo (fonte da verdade unica: o markdown do produtor)
# --------------------------------------------------------------------------


def _carregar_catalogo() -> dict:
    texto = PRODUTOR_SPEC.read_text(encoding="utf-8")
    bloco = re.search(r"```json risk-signals\n(.*?)\n```", texto, re.DOTALL)
    assert bloco is not None, (
        "bloco ```json risk-signals``` ausente em "
        f"{PRODUTOR_SPEC.relative_to(REPO_ROOT)}; o catalogo de risco do PASSO 2R "
        "e a fonte da verdade do gate e nao pode sumir do spec"
    )
    return json.loads(bloco.group(1))


CATALOGO = _carregar_catalogo()
PISO = (CATALOGO["floor_tier"]["model"], CATALOGO["floor_tier"]["effort"])


# --------------------------------------------------------------------------
# Implementacao de referencia da regra descrita ao lado do catalogo
# --------------------------------------------------------------------------


def _sinais_que_casam(texto: str) -> list[str]:
    return [s["id"] for s in CATALOGO["sinais"] if re.search(s["regex"], texto)]


def _risk_score(texto: str) -> int:
    casados = set(_sinais_que_casam(texto))
    return sum(s["peso"] for s in CATALOGO["sinais"] if s["id"] in casados)


def _tier_por_risco(score: int) -> tuple[str, str] | None:
    for faixa in CATALOGO["tier_por_risco"]:
        if score >= faixa["risk_score_min"]:
            return (faixa["model"], faixa["effort"])
    return None


def _maior_tier(a: tuple[str, str], b: tuple[str, str] | None) -> tuple[str, str]:
    if b is None:
        return a
    return a if _TIER_ORDEM.index(a) >= _TIER_ORDEM.index(b) else b


def classificar(titulo: str, corpo: str = "", tier_calculado: tuple[str, str] = PISO) -> dict:
    """Aplica o PASSO 2R sobre um item. Espelha o texto do spec, passo a passo."""
    texto = f"{titulo}\n{corpo}"
    sinais = _sinais_que_casam(texto)
    score = _risk_score(texto)
    por_risco = _tier_por_risco(score)
    efetivo = _maior_tier(tier_calculado, por_risco)
    if efetivo != tier_calculado:
        reason = "risco de dominio: " + ",".join(sorted(sinais))
    else:
        reason = None
    return {
        "risk_signals": sinais,
        "risk_score": score,
        "tier_calculado": {"model": tier_calculado[0], "effort": tier_calculado[1]},
        "tier_efetivo": {"model": efetivo[0], "effort": efetivo[1]},
        "override_reason": reason,
    }


def detectar_anomalia(classificados: list[dict]) -> dict | None:
    total = len(classificados)
    if total == 0:
        return None
    cfg = CATALOGO["anomaly_detector"]
    no_piso = [
        c for c in classificados
        if (c["tier_efetivo"]["model"], c["tier_efetivo"]["effort"]) == PISO
    ]
    # Suspeito e o item que esta no piso APESAR de carregar risco. Contar risco
    # na lista inteira faria o detector gritar depois do PASSO 2R ter acertado.
    suspeitos = [c for c in no_piso if c["risk_score"] >= 20]
    piso_ratio = len(no_piso) / total
    risco_no_piso_ratio = len(suspeitos) / total
    if (
        piso_ratio >= cfg["piso_ratio_min"]
        and risco_no_piso_ratio >= cfg["risco_no_piso_ratio_min"]
    ):
        return {"piso_ratio": piso_ratio, "risco_no_piso_ratio": risco_no_piso_ratio}
    return None


# --------------------------------------------------------------------------
# Fixture derivada dos titulos REAIS do 08-19
# --------------------------------------------------------------------------

# Titulos vindos da fixture CONGELADA da Task 05/13.2, nunca do diretorio vivo:
# o caso 08-19 e evidencia historica, nao corpus mutavel de teste. Os itens de
# `risco` sao os que obrigaram o override humano; os de `controle` sao
# encanamento sem consequencia de dominio, que devem continuar no piso.
_FIXTURE = json.loads(FIXTURE_08_19.read_text(encoding="utf-8"))
ITENS_08_19_RISCO = _FIXTURE["risco"]
ITENS_08_19_CONTROLE = _FIXTURE["controle"]


# --------------------------------------------------------------------------
# Testes - catalogo
# --------------------------------------------------------------------------


def test_catalogo_tem_os_sete_eixos_da_task():
    esperados = {
        "seguranca",
        "dados_pessoais",
        "contrato_publico",
        "migracao",
        "concorrencia",
        "integracao_externa",
        "reversibilidade",
    }
    assert {s["id"] for s in CATALOGO["sinais"]} == esperados


def test_todos_os_regex_compilam():
    for sinal in CATALOGO["sinais"]:
        re.compile(sinal["regex"])  # levanta re.error se o spec quebrar


def test_piso_do_catalogo_bate_com_o_piso_da_task_10():
    # O eixo de risco nao pode inventar um piso proprio: ele promove a partir
    # do mesmo `sonnet/standard` que a Task 10 travou.
    assert PISO == ("sonnet", "standard")


def test_faixas_de_risco_sao_monotonicas():
    minimos = [f["risk_score_min"] for f in CATALOGO["tier_por_risco"]]
    assert minimos == sorted(minimos, reverse=True), (
        "tier_por_risco precisa estar em ordem decrescente de risk_score_min; "
        "a regra le a PRIMEIRA faixa que casa"
    )
    for faixa in CATALOGO["tier_por_risco"]:
        tier = (faixa["model"], faixa["effort"])
        assert tier in _TIER_ORDEM
        assert _TIER_ORDEM.index(tier) > _TIER_ORDEM.index(PISO), (
            "toda faixa de risco precisa promover acima do piso"
        )


# --------------------------------------------------------------------------
# Testes - o caso 08-19 (Aceite principal da Task 11)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("item_id,titulo", sorted(ITENS_08_19_RISCO.items()))
def test_itens_de_risco_do_08_19_nao_caem_no_piso(item_id, titulo):
    resultado = classificar(titulo)
    tier = (resultado["tier_efetivo"]["model"], resultado["tier_efetivo"]["effort"])
    assert tier != PISO, (
        f"item {item_id} ({titulo!r}) voltou para o piso {PISO}; foi exatamente "
        "isso que obrigou o override humano no 08-19"
    )
    assert resultado["risk_signals"], f"item {item_id} nao casou nenhum sinal de risco"
    assert resultado["override_reason"], (
        f"item {item_id} foi promovido sem registrar override_reason"
    )


def test_sinais_esperados_por_item_de_risco():
    # Trava a razao, nao so o resultado: se um regex parar de casar o motivo
    # certo, o item pode continuar promovido pelo motivo errado.
    esperado = {
        "009": {"integracao_externa"},
        "021": {"seguranca", "integracao_externa"},
        "029": {"seguranca"},
        "030": {"seguranca"},
        "032": {"dados_pessoais"},
    }
    for item_id, ids in esperado.items():
        assert set(classificar(ITENS_08_19_RISCO[item_id])["risk_signals"]) == ids, (
            f"sinais de risco do item {item_id} mudaram"
        )


def test_item_de_revogacao_mais_terceiro_chega_no_topo():
    # 021 acumula seguranca (25) + integracao externa (20) = 45.
    resultado = classificar(ITENS_08_19_RISCO["021"])
    assert resultado["risk_score"] == 45
    assert resultado["tier_efetivo"] == {"model": "opus", "effort": "high"}


def test_itens_de_encanamento_do_08_19_continuam_no_piso():
    # O gate promove por consequencia, nao por paranoia: task sem risco de
    # dominio nao pode ser inflada, senao o eixo vira ruido e o operador
    # volta a ignorar a distribuicao.
    for item_id, titulo in ITENS_08_19_CONTROLE.items():
        resultado = classificar(titulo)
        assert resultado["risk_signals"] == [], (
            f"item de controle {item_id} ({titulo!r}) casou {resultado['risk_signals']}"
        )
        assert resultado["tier_efetivo"] == {"model": "sonnet", "effort": "standard"}
        assert resultado["override_reason"] is None


def test_fixture_congelada_cobre_os_dois_lados_do_caso():
    # Sem os itens de controle a fixture provaria so metade: que o gate promove.
    # A outra metade - que ele NAO infla task inocente - e o que impede o eixo
    # de risco de virar ruido.
    assert len(ITENS_08_19_RISCO) == 5
    assert len(ITENS_08_19_CONTROLE) == 3
    assert "_procedencia" in _FIXTURE, "fixture sem registro de procedencia"


# --------------------------------------------------------------------------
# Testes - precedencia (risco promove, nunca rebaixa)
# --------------------------------------------------------------------------


def test_risco_nao_rebaixa_o_que_o_esforco_ja_pediu():
    # Task pesada de encanamento continua opus/high mesmo com risco zero.
    resultado = classificar("Preparacao", tier_calculado=("opus", "high"))
    assert resultado["tier_efetivo"] == {"model": "opus", "effort": "high"}
    assert resultado["override_reason"] is None


def test_esforco_alto_e_risco_baixo_mantem_o_tier_do_esforco():
    resultado = classificar(
        ITENS_08_19_RISCO["009"], tier_calculado=("opus", "high")
    )
    assert resultado["risk_score"] == 20
    assert resultado["tier_efetivo"] == {"model": "opus", "effort": "high"}


def test_score_abaixo_do_minimo_nao_promove():
    resultado = classificar("Ajustar espacamento do rodape")
    assert resultado["risk_score"] < 20
    assert resultado["tier_efetivo"] == {"model": "sonnet", "effort": "standard"}


# --------------------------------------------------------------------------
# Testes - detector de distribuicao anomala
# --------------------------------------------------------------------------


def test_detector_dispara_na_assinatura_do_08_19():
    # Reconstroi a forma do incidente: quase tudo no piso, com risco espalhado.
    # `tier_calculado` fixo no piso simula a heuristica de esforco colapsada;
    # o detector precisa enxergar isso ANTES do operador.
    classificados = [
        {
            "risk_signals": _sinais_que_casam(t),
            "risk_score": _risk_score(t),
            "tier_efetivo": {"model": PISO[0], "effort": PISO[1]},
        }
        for t in list(ITENS_08_19_RISCO.values()) + ["Encanamento %d" % i for i in range(12)]
    ]
    alerta = detectar_anomalia(classificados)
    assert alerta is not None, (
        "detector nao disparou na propria assinatura que originou a Task 11"
    )
    assert alerta["piso_ratio"] >= CATALOGO["anomaly_detector"]["piso_ratio_min"]
    assert (
        alerta["risco_no_piso_ratio"]
        >= CATALOGO["anomaly_detector"]["risco_no_piso_ratio_min"]
    )


def test_detector_fica_quieto_quando_o_risco_foi_promovido():
    # Mesma lista, agora classificada corretamente pelo PASSO 2R: os itens de
    # risco sairam do piso, logo nao ha anomalia a reportar.
    classificados = [classificar(t) for t in ITENS_08_19_RISCO.values()]
    classificados += [classificar("Encanamento %d" % i) for i in range(12)]
    assert detectar_anomalia(classificados) is None


def test_detector_fica_quieto_em_lista_toda_no_piso_sem_risco():
    # Loop de refactor cosmetico: 100% no piso e legitimo. Alertar aqui seria
    # o ruido que ensina o operador a ignorar o alerta.
    classificados = [classificar("Renomear variavel %d" % i) for i in range(20)]
    assert all(
        (c["tier_efetivo"]["model"], c["tier_efetivo"]["effort"]) == PISO
        for c in classificados
    )
    assert detectar_anomalia(classificados) is None


def test_detector_nao_quebra_em_lista_vazia():
    assert detectar_anomalia([]) is None


# --------------------------------------------------------------------------
# Testes - contrato de registro no artefato
# --------------------------------------------------------------------------


def test_spec_declara_os_campos_de_auditoria_de_override():
    texto = PRODUTOR_SPEC.read_text(encoding="utf-8")
    for campo in ("tier_calculado", "tier_efetivo", "override_reason", "risk_score", "risk_signals"):
        assert f"`{campo}`" in texto, (
            f"campo {campo} nao esta documentado no produtor; sem registro no "
            "artefato o override humano continua invisivel para a proxima analise"
        )
    assert "sizing_distribution_alert" in texto


def test_classificacao_devolve_o_pacote_de_auditoria_completo():
    resultado = classificar(ITENS_08_19_RISCO["032"])
    assert set(resultado) == {
        "risk_signals",
        "risk_score",
        "tier_calculado",
        "tier_efetivo",
        "override_reason",
    }
    assert resultado["tier_calculado"] == {"model": "sonnet", "effort": "standard"}
    assert resultado["tier_efetivo"] != resultado["tier_calculado"]
    assert resultado["override_reason"].startswith("risco de dominio:")
