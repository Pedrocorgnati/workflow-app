"""Gate da Task 33: nenhum caminho de termino do brainstorm morre calado.

O defeito que esta task fecha nao era "falta telemetria" -- era que UM dos
nove terminos do handler tinha evento estruturado (`t3_publish_failed`) e os
outros oito nao, entre eles o gate de reentrancia, que nem toast emitia. Um
clique engolido ali era indistinguivel de um clique que nunca chegou.

Por que o gate principal e sintatico e nao comportamental
---------------------------------------------------------
Um teste por reason prova que os nove pontos de HOJE registram. Nao prova
nada sobre o DECIMO -- e foi exatamente assim que o handler chegou a nove
saidas com uma instrumentada: cada `return` novo nasceu sozinho e ninguem
percebeu. `test_todo_return_do_handler_registra` percorre a AST e exige que
todo `ast.Return` tenha uma chamada de registro imediatamente antes, entao um
`return` novo reprova por existir, sem que ninguem precise lembrar de
adicionar um teste para ele.

O gate sintatico sozinho tambem nao basta: ele aceitaria `_registrar("ok")`
em todo lugar. Por isso os testes comportamentais abaixo verificam o par
(caminho percorrido -> reason gravado) lendo o sidecar de verdade.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from workflow_app import brainstorm_telemetry as tel
from workflow_app.main_window import MainWindow

pytestmark = pytest.mark.timeout(15)

_SRC_HANDLER = Path(MainWindow.__module__.replace(".", "/"))
_RAIZ_SRC = Path(__file__).resolve().parents[1] / "src" / "workflow_app"
_MAIN_WINDOW_PY = _RAIZ_SRC / "main_window.py"
_BOTAO_PY = _RAIZ_SRC / "widgets" / "mcp_prompt_button.py"


# ---------------------------------------------------------------------------
# Sidecar isolado
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _sidecar(tmp_path):
    """Redireciona o sidecar e restaura o estado global do modulo.

    Sem a restauracao, o primeiro teste daqui deixaria `_LOG_DIR` apontando
    para um `tmp_path` ja destruido e os testes seguintes da suite gravariam
    em lugar nenhum -- silenciosamente, porque `_write_jsonl` engole `OSError`.
    """
    antes = (tel._LOG_DIR, tel._JSONL_PATH, tel._strict, tel._seq)
    tel._reset_for_tests(log_dir=tmp_path / "logs", strict=True)
    yield
    tel._LOG_DIR, tel._JSONL_PATH, tel._strict, tel._seq = antes


def _eventos() -> list[dict]:
    caminho = tel.jsonl_path()
    if not caminho.is_file():
        return []
    return [
        json.loads(linha)
        for linha in caminho.read_text(encoding="utf-8").splitlines()
        if linha.strip()
    ]


def _reasons() -> list[str]:
    return [e["reason"] for e in _eventos()]


# ---------------------------------------------------------------------------
# Gate sintatico
# ---------------------------------------------------------------------------


def _funcao(caminho: Path, classe: str, nome: str) -> ast.FunctionDef:
    """O metodo `nome` de `classe`, exigindo que exista exatamente um.

    Varrer o modulo inteiro com `ast.walk` devolvia a PRIMEIRA definicao
    com aquele nome em qualquer lugar do arquivo. Uma funcao homonima
    acima da classe -- helper de modulo, metodo de outra classe, ou uma
    definicao morta deixada para tras -- sequestrava o gate inteiro, que
    passava a auditar codigo que nao e o despachado e aprovava o handler
    real sem nunca o ter lido.

    Exigir unicidade fecha os dois lados: a homonima de fora nao e vista,
    e duas dentro da classe reprovam em vez de o gate escolher uma.
    """
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    classes = [
        no for no in ast.walk(arvore)
        if isinstance(no, ast.ClassDef) and no.name == classe
    ]
    assert len(classes) == 1, (
        f"esperava exatamente uma classe {classe} em {caminho.name}, "
        f"achei {len(classes)}"
    )
    achadas = [
        no for no in classes[0].body
        if isinstance(no, ast.FunctionDef) and no.name == nome
    ]
    assert len(achadas) == 1, (
        f"esperava exatamente um metodo {classe}.{nome} em {caminho.name}, "
        f"achei {len(achadas)}"
    )
    return achadas[0]


def _reason_registrado(stmt: ast.stmt, nomes: tuple[str, ...]) -> str | None:
    """Reason literal se `stmt` e uma chamada de registro; senao None.

    Aceita tanto o helper local (`_registrar`, `self._registrar_bloqueio`)
    quanto a chamada direta ao modulo -- o gate de reentrancia dispara antes
    de o helper existir e precisa chamar `record_dispatch` na mao.
    """
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return None
    chamada = stmt.value
    alvo = chamada.func
    if isinstance(alvo, ast.Attribute):
        # O receptor importa. Sem esta checagem, `logger.record_dispatch(
        # reason="ok")` -- ou qualquer objeto com um atributo de mesmo
        # nome -- satisfazia o gate sem escrever evento nenhum: o gate lia
        # o nome do atributo e nunca perguntava em quem.
        if (
            not isinstance(alvo.value, ast.Name)
            or alvo.value.id not in _RECEPTORES_VALIDOS
        ):
            return None
        rotulo = alvo.attr
    elif isinstance(alvo, ast.Name):
        rotulo = alvo.id
    else:
        return None
    if rotulo not in nomes:
        return None
    for arg in chamada.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    for kw in chamada.keywords:
        if kw.arg == "reason" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    raise AssertionError(f"chamada de registro sem reason literal na linha {stmt.lineno}")


#: Receptores aceitos numa chamada de registro. `brainstorm_telemetry` e o
#: modulo; `self` e o widget. Qualquer outro objeto com um atributo
#: homonimo e um impostor do ponto de vista deste gate.
_RECEPTORES_VALIDOS = ("brainstorm_telemetry", "self")

_HELPERS_ANINHADOS = ("_registrar",)


def _blocos(fn: ast.AST):
    """Toda lista de statements dentro de `fn`, incluindo else e finally.

    O corpo do helper aninhado fica de fora: la dentro `reason` e o parametro
    repassado, nao um literal, e le-lo como ponto de termino faria o gate
    acusar o proprio mecanismo que ele existe para verificar.
    """
    for no in ast.walk(fn):
        if isinstance(no, ast.FunctionDef) and no.name in _HELPERS_ANINHADOS:
            continue
        for campo in ("body", "orelse", "finalbody"):
            lista = getattr(no, campo, None)
            if isinstance(lista, list) and lista and isinstance(lista[0], ast.stmt):
                yield lista


_NOMES_HANDLER = ("_registrar", "record_dispatch")
_NOMES_BOTAO = ("_registrar_bloqueio",)


def _terminos(fn: ast.AST, nomes: tuple[str, ...]) -> tuple[list[int], int]:
    """(linhas orfas, total de terminos) -- `return` E `raise`.

    `raise` entrou junto com `return` por duas razoes. A primeira e que ele
    E um termino real: o `except Exception` do handler sobe a excecao
    depois de registrar, e cobrir so `return` deixaria esse caminho fora do
    gate. A segunda e adversarial: enquanto o gate olhava so `return`,
    inserir um `raise` (ou um `sys.exit()`) ANTES do par
    `_registrar(...)`/`return` ja existente tornava os dois inalcancaveis
    sem que a AST reclamasse -- o codigo ficava mudo e o gate, verde.
    """
    orfaos: list[int] = []
    total = 0
    for bloco in _blocos(fn):
        for i, stmt in enumerate(bloco):
            if not isinstance(stmt, (ast.Return, ast.Raise)):
                continue
            total += 1
            anterior = bloco[i - 1] if i else None
            if anterior is None or _reason_registrado(anterior, nomes) is None:
                orfaos.append(stmt.lineno)
    return orfaos, total


def test_todo_termino_do_handler_registra():
    """Um `return` ou `raise` sem registro imediatamente antes reprova.

    E o gate que sobrevive ao autor: o decimo primeiro ponto de termino nao
    precisa que ninguem se lembre dele.
    """
    fn = _funcao(_MAIN_WINDOW_PY, "MainWindow", "_on_mcp_prompt_requested")
    orfaos, total = _terminos(fn, _NOMES_HANDLER)
    assert total >= 9, f"esperava ao menos 9 terminos no handler, achei {total}"
    assert orfaos == [], (
        "terminos sem registro de telemetria imediatamente antes (linhas): "
        f"{orfaos}. Todo caminho de termino grava um evento -- inclusive o "
        "novo."
    )


def test_o_helper_de_registro_do_handler_e_unico_e_delega_ao_modulo():
    """`_registrar` precisa SER o registro, nao apenas se chamar assim.

    Todo o gate sintatico se apoia no nome `_registrar`. Uma segunda
    definicao no-op sombreando a primeira -- ou uma unica definicao que
    parou de chamar `record_dispatch` -- deixava os dez pontos de termino
    "instrumentados" gravando exatamente nada, com esta suite verde.
    """
    fn = _funcao(_MAIN_WINDOW_PY, "MainWindow", "_on_mcp_prompt_requested")
    defs = [
        no for no in ast.walk(fn)
        if isinstance(no, ast.FunctionDef) and no.name == "_registrar"
    ]
    assert len(defs) == 1, (
        f"esperava uma unica definicao de _registrar, achei {len(defs)} "
        f"(linhas {[d.lineno for d in defs]}); a ultima sombra as anteriores"
    )
    delega = [
        no for no in ast.walk(defs[0])
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Attribute)
        and no.func.attr == "record_dispatch"
        and isinstance(no.func.value, ast.Name)
        and no.func.value.id == "brainstorm_telemetry"
    ]
    assert delega, (
        "_registrar nao chama brainstorm_telemetry.record_dispatch: o "
        "helper virou no-op e todo o gate acima passou a medir aparencia"
    )


def test_o_handler_nao_esconde_termino_atras_de_branch_morto():
    """Duas evasoes que a AST sozinha nao ve.

    `_blocos` percorre branches mortos: `if False: _registrar("ok")` fazia
    o reason aparecer no vocabulario sem nunca executar. E `sys.exit()` /
    `os._exit()` terminam o processo sem `return` nem `raise`, escapando
    do gate de terminos. Nenhuma das duas tem uso legitimo num slot de
    clique, entao a regra e a proibicao, nao a deteccao.
    """
    fn = _funcao(_MAIN_WINDOW_PY, "MainWindow", "_on_mcp_prompt_requested")
    constantes = [
        no.lineno for no in ast.walk(fn)
        if isinstance(no, ast.If) and isinstance(no.test, ast.Constant)
    ]
    assert constantes == [], (
        f"`if` de condicao constante no handler (linhas {constantes}): "
        "branch morto que o gate sintatico conta como instrumentado"
    )
    saidas = [
        no.lineno for no in ast.walk(fn)
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Attribute)
        and no.func.attr in ("exit", "_exit", "abort")
    ]
    assert saidas == [], (
        f"termino de processo dentro do handler (linhas {saidas}): "
        "sai sem `return`, sem `raise` e sem evento"
    )


def test_o_caminho_de_sucesso_do_handler_tambem_registra():
    """Sucesso nao tem `return`: termina caindo no `finally`.

    Sem esta checagem o gate acima cobriria as oito falhas e deixaria o unico
    caminho feliz mudo, que e o pior lugar para faltar dado: sem ele nao da
    para calcular taxa de erro, so contar erros.
    """
    fn = _funcao(_MAIN_WINDOW_PY, "MainWindow", "_on_mcp_prompt_requested")
    externos = [
        no for no in ast.walk(fn) if isinstance(no, ast.Try) and no.finalbody
    ]
    assert externos, "o handler perdeu o try/finally do gate de reentrancia"
    ultimos = [
        _reason_registrado(t.body[-1], _NOMES_HANDLER) for t in externos
    ]
    assert "ok" in ultimos, (
        "o ultimo statement do try com finally deveria ser o registro de "
        f"sucesso; achei {ultimos}"
    )


def test_os_reasons_no_codigo_sao_exatamente_os_declarados():
    """Fonte e vocabulario nao podem divergir nas duas direcoes.

    Reason no codigo fora do conjunto: o modo estrito levanta em runtime.
    Reason declarado e nunca usado: caminho que alguem previu, instrumentou
    no vocabulario e esqueceu de ligar -- some do sidecar sem nunca acusar.
    """
    fn = _funcao(_MAIN_WINDOW_PY, "MainWindow", "_on_mcp_prompt_requested")
    achados = Counter(
        r
        for bloco in _blocos(fn)
        for stmt in bloco
        if (r := _reason_registrado(stmt, _NOMES_HANDLER)) is not None
    )
    assert set(achados) == set(tel.HANDLER_REASONS), (
        f"faltando no codigo: {sorted(set(tel.HANDLER_REASONS) - set(achados))}; "
        f"nao declarados: {sorted(set(achados) - set(tel.HANDLER_REASONS))}"
    )
    # Contagem, e nao so pertinencia. Com conjunto, um decimo primeiro
    # termino instrumentado com um reason JA usado -- `_registrar("ok")`
    # antes de um `return` de falha, o erro mais natural de se cometer --
    # desaparecia na deduplicacao: o gate aprovava, e o sidecar passava a
    # contar uma falha como sucesso.
    repetidos = {r: n for r, n in achados.items() if n > 1}
    assert repetidos == {}, (
        f"reason usado em mais de um ponto de termino: {repetidos}. Cada "
        "caminho precisa do seu, senao dois caminhos distintos viram a "
        "mesma linha no sidecar."
    )


def test_todo_return_pre_emit_do_botao_registra():
    """Mesmo gate no widget: os tres gates antes do `emit`."""
    fn = _funcao(_BOTAO_PY, "MCPPromptButton", "_on_clicked")
    orfaos, total = _terminos(fn, _NOMES_BOTAO)
    # Piso explicito. Sem ele, apagar os tres `return` deixava `orfaos`
    # vazio e o gate verde: um slot que nao bloqueia nada satisfaz
    # trivialmente "todo bloqueio registra".
    assert total >= 3, (
        f"esperava ao menos 3 terminos pre-emit em _on_clicked, achei {total}"
    )
    assert orfaos == [], f"returns sem registro em _on_clicked: {orfaos}"


def test_os_reasons_do_botao_sao_exatamente_os_declarados():
    fn = _funcao(_BOTAO_PY, "MCPPromptButton", "_on_clicked")
    achados = {
        r
        for bloco in _blocos(fn)
        for stmt in bloco
        if (r := _reason_registrado(stmt, _NOMES_BOTAO)) is not None
    }
    assert achados == set(tel.WIDGET_REASONS), (
        f"faltando no codigo: {sorted(set(tel.WIDGET_REASONS) - achados)}; "
        f"nao declarados: {sorted(achados - set(tel.WIDGET_REASONS))}"
    )


# ---------------------------------------------------------------------------
# Comportamento: handler
# ---------------------------------------------------------------------------


class _Radio:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:  # noqa: N802 (espelha a API do Qt)
        return self._checked


class _Stub:
    """Mesma superficie usada por `test_brainstorm_dispatch_hardening`."""

    _prompt_in_flight = False

    def __init__(self, repo_root: Path, md_path: str | None, publica: bool = True) -> None:
        self._fake_root = repo_root
        self._brainstorm_md_path = md_path
        self._publica = publica
        self.publish_calls: list[tuple[str, int]] = []

    def _systemforge_root(self) -> Path:
        return self._fake_root

    def _current_llm_provider(self) -> str:
        return "kimi"

    def _rel_to_root(self, p: str) -> str:
        return "blacksmith/brainstorm-mcp/ideia.md"

    def _codex_terminal_available(self) -> bool:
        return True

    def _publish_to_specific_terminal(self, text: str, terminal: int) -> bool:
        self.publish_calls.append((text, terminal))
        return self._publica

    _clear_brainstorm_md_selection = MainWindow._clear_brainstorm_md_selection


class _Sinais:
    """Grava o que o handler emitiu, em vez de descartar.

    Os fakes anteriores eram `lambda ...: None`: nenhum teste desta suite
    conseguia notar remocao, duplicacao ou reordenacao de toast e de
    `dispatch_result`. O caso mais gritante era o da reentrancia, cujo
    docstring AFIRMA que o caminho segue sem toast e sem `dispatch_result`
    e cujo corpo nao observava nenhum dos dois -- a afirmacao valia por
    confianca. Agora os dois sinais sao dados do teste.
    """

    def __init__(self) -> None:
        self.toasts: list[tuple[str, str]] = []
        self.dispatch: list[tuple[str, bool]] = []


def _install_fakes(monkeypatch, *, build=None) -> _Sinais:
    import workflow_app.main_window as mw

    sinais = _Sinais()
    monkeypatch.setattr(
        mw, "QTimer",
        type("QT", (), {"singleShot": staticmethod(lambda ms, fn: None)}),
    )
    monkeypatch.setattr(mw, "signal_bus", type("SB", (), {
        "toast_requested": type("T", (), {
            "emit": staticmethod(lambda m, lvl: sinais.toasts.append((m, lvl)))
        })(),
        "dispatch_result": type("D", (), {
            "emit": staticmethod(lambda b, ok: sinais.dispatch.append((b, ok)))
        })(),
    })())
    monkeypatch.setattr(
        mw, "build_prompt", build or (lambda meta, md_ref, root: "PROMPT FINAL"),
    )
    return sinais


_PAYLOAD = {
    "button_id": "mcp-prompt-btn-otimizar",
    "label": "Otimizar",
    "action": "Otimizar",
    "agent_name": "x",
    "agent_path": "agents/x.md",
    "button_type": "Claude",
    "target_path": "terminal-interactive-output",
    "target_path_edit_inplace": True,
    "testid_slug": "otimizar",
}


def _md_real(tmp_path: Path) -> Path:
    alvo = tmp_path / "blacksmith" / "brainstorm-mcp" / "ideia.md"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text("# ideia\n", encoding="utf-8")
    return alvo


def test_sucesso_grava_ok_com_terminal_e_tamanho(monkeypatch, tmp_path):
    sinais = _install_fakes(monkeypatch)
    md = _md_real(tmp_path)
    stub = _Stub(tmp_path, str(md))

    MainWindow._on_mcp_prompt_requested(stub, dict(_PAYLOAD))  # type: ignore[arg-type]

    (ev,) = _eventos()
    assert ev["reason"] == "ok"
    assert ev["ok"] is True
    assert ev["event"] == tel.EVENT_DISPATCH
    assert ev["terminal"] == 1
    assert ev["prompt_chars"] == len("PROMPT FINAL")
    assert ev["testid_slug"] == "otimizar"
    # `artifact_id` e `source_kind` sao os dois campos que vinham de
    # helpers e nao do payload: desligar os dois de `_ctx` deixava toda a
    # suite verde, porque nenhum teste comportamental os observava.
    assert ev["artifact_id"] == tel.artifact_id(md, tmp_path)
    assert ev["artifact_id"] != ""
    assert ev["source_kind"] == "unknown", (
        "o payload deste teste nao carrega `prompt`, entao nao ha corpo em "
        "disco para classificar -- `unknown` e a resposta honesta"
    )
    assert sinais.dispatch == [("mcp-prompt-btn-otimizar", True)]
    assert sinais.toasts == [], "sucesso nao emite toast"


def test_md_sumido_grava_md_missing(monkeypatch, tmp_path):
    _install_fakes(monkeypatch)
    fantasma = tmp_path / "blacksmith" / "brainstorm-mcp" / "ideia.md"
    stub = _Stub(tmp_path, str(fantasma))

    MainWindow._on_mcp_prompt_requested(stub, dict(_PAYLOAD))  # type: ignore[arg-type]

    assert _reasons() == ["md_missing"]


def test_sem_md_selecionado_grava_no_md_selected(monkeypatch, tmp_path):
    _install_fakes(monkeypatch)
    stub = _Stub(tmp_path, None)

    MainWindow._on_mcp_prompt_requested(stub, dict(_PAYLOAD))  # type: ignore[arg-type]

    assert _reasons() == ["no_md_selected"]


def test_rota_ambigua_grava_sem_inventar_terminal(monkeypatch, tmp_path):
    """`terminal` fica ausente: com 2 alvos nao existe UM terminal.

    Gravar `len(targets)` ali faria um agregador contar um aborto com tres
    alvos marcados como um despacho para o T3.
    """
    _install_fakes(monkeypatch)
    stub = _Stub(tmp_path, str(_md_real(tmp_path)))
    stub._chk_route_t1 = _Radio(True)
    stub._chk_route_t2 = _Radio(True)
    stub._chk_route_t3 = _Radio(False)

    MainWindow._on_mcp_prompt_requested(stub, dict(_PAYLOAD))  # type: ignore[arg-type]

    (ev,) = _eventos()
    assert ev["reason"] == "route_ambiguous"
    assert ev["ok"] is False
    assert ev["terminal"] is None, (
        "ausencia explicita, nao um indice inventado: `null` continua "
        "distinguivel de 1, 2 ou 3 em qualquer agregacao"
    )


def test_publish_false_grava_publish_failed(monkeypatch, tmp_path):
    _install_fakes(monkeypatch)
    stub = _Stub(tmp_path, str(_md_real(tmp_path)), publica=False)

    MainWindow._on_mcp_prompt_requested(stub, dict(_PAYLOAD))  # type: ignore[arg-type]

    (ev,) = _eventos()
    assert ev["reason"] == "publish_failed"
    assert ev["ok"] is False
    assert ev["terminal"] == 1


def test_build_prompt_recusado_grava_prompt_rejected(monkeypatch, tmp_path):
    def _recusa(meta, md_ref, root):
        raise ValueError("prompt invalido")

    _install_fakes(monkeypatch, build=_recusa)
    stub = _Stub(tmp_path, str(_md_real(tmp_path)))

    MainWindow._on_mcp_prompt_requested(stub, dict(_PAYLOAD))  # type: ignore[arg-type]

    assert _reasons() == ["prompt_rejected"]


def test_defeito_de_tipo_grava_prompt_build_error(monkeypatch, tmp_path):
    def _quebra(meta, md_ref, root):
        raise TypeError("assinatura mudou")

    _install_fakes(monkeypatch, build=_quebra)
    stub = _Stub(tmp_path, str(_md_real(tmp_path)))

    MainWindow._on_mcp_prompt_requested(stub, dict(_PAYLOAD))  # type: ignore[arg-type]

    assert _reasons() == ["prompt_build_error"]


def test_excecao_ao_publicar_grava_publish_exception(monkeypatch, tmp_path):
    _install_fakes(monkeypatch)
    stub = _Stub(tmp_path, str(_md_real(tmp_path)))

    def _explode(text, terminal):
        raise RuntimeError("terminal morreu")

    stub._publish_to_specific_terminal = _explode  # type: ignore[assignment]

    MainWindow._on_mcp_prompt_requested(stub, dict(_PAYLOAD))  # type: ignore[arg-type]

    assert _reasons() == ["publish_exception"]


def test_reentrancia_grava_in_flight_o_ponto_cego_original(monkeypatch, tmp_path):
    """O gate que nao emitia toast nem `dispatch_result`.

    Continua silencioso na UI de proposito -- o segundo clique de um
    double-click nao merece toast -- mas agora deixa rastro.
    """
    sinais = _install_fakes(monkeypatch)
    stub = _Stub(tmp_path, str(_md_real(tmp_path)))
    stub._prompt_in_flight = True

    MainWindow._on_mcp_prompt_requested(stub, dict(_PAYLOAD))  # type: ignore[arg-type]

    assert sinais.toasts == [], "o segundo clique de um double-click nao merece toast"
    assert sinais.dispatch == [], (
        "nem `dispatch_result`: o botao de origem nao pode desmarcar o "
        "checkbox do disparo que ainda esta em voo"
    )
    (ev,) = _eventos()
    assert ev["reason"] == "in_flight"
    assert ev["button_id"] == "mcp-prompt-btn-otimizar"
    assert ev["testid_slug"] == "otimizar", (
        "o gate dispara antes de `button_id` ser calculado e precisa ler do "
        "payload; se ler de uma variavel ainda inexistente, fica vazio"
    )
    assert stub.publish_calls == []


def test_os_dois_eixos_de_provider_sao_gravados(monkeypatch, tmp_path):
    """`type-selector-radio-input` pedido, provider corrente resolvido.

    So o par mede a degradacao: so o resolvido apaga o que o operador pediu,
    so o pedido esconde a queda para outro provider.
    """
    _install_fakes(monkeypatch)
    stub = _Stub(tmp_path, str(_md_real(tmp_path)))
    payload = dict(_PAYLOAD, button_type="type-selector-radio-input")

    MainWindow._on_mcp_prompt_requested(stub, payload)  # type: ignore[arg-type]

    (ev,) = _eventos()
    assert ev["requested_provider"] == "type-selector-radio-input"
    assert ev["resolved_provider"] == "kimi"


def test_main_mimo_grava_mimo_sem_degradar(monkeypatch, tmp_path):
    """Espelho do caso qwen: Main=MiMo tem rotulo de brainstorm proprio.

    MiMo esta em `_BRAINSTORM_PROVIDER_LABELS`, entao o resolvido e o proprio
    slug e nao a queda para Claude que qwen/grok sofrem. Sem toggles de rota,
    o fallback do radio manda o despacho ao terminal do worker (o mesmo do
    kimi), nunca ao T1 de Claude.
    """
    sinais = _install_fakes(monkeypatch)
    stub = _Stub(tmp_path, str(_md_real(tmp_path)))
    stub._current_llm_provider = lambda: "mimo"  # type: ignore[assignment]
    payload = dict(_PAYLOAD, button_type="type-selector-radio-input")

    MainWindow._on_mcp_prompt_requested(stub, payload)  # type: ignore[arg-type]

    (ev,) = _eventos()
    assert ev["reason"] == "ok"
    assert ev["requested_provider"] == "type-selector-radio-input"
    assert ev["resolved_provider"] == "mimo", (
        "MiMo tem rotulo de brainstorm: o registro grava o slug que executou, "
        "sem a degradacao para Claude reservada a qwen/grok"
    )
    assert ev["terminal"] == 2, "sem toggles, Main MiMo herda o terminal do worker"
    assert [terminal for _, terminal in stub.publish_calls] == [2]
    assert sinais.dispatch == [("mcp-prompt-btn-otimizar", True)]


_PROMPT_MARCADO = (
    "CABECALHO-DO-PROMPT-QUE-NAO-PODE-VAZAR\n"
    "corpo com segredo ghp_" + "C" * 36 + "\n"
    "e uma segunda linha inteira de conteudo confidencial do operador"
)


def test_nenhum_evento_carrega_path_nem_o_prompt(monkeypatch, tmp_path):
    """O sidecar identifica o artefato, nunca o localiza nem o transcreve.

    A versao anterior procurava so o literal completo `"PROMPT FINAL"`.
    Gravar `prompt_final[:8]`, um hash do prompt, ou qualquer pedaco dele
    passava -- e a politica do modulo proibe o prompt em TODA forma,
    inclusive truncado e hasheado. Aqui o prompt e longo e marcado, e o
    teste varre por fragmento e pelos tres digests obvios.
    """
    _install_fakes(
        monkeypatch, build=lambda meta, md_ref, root: _PROMPT_MARCADO,
    )
    md = _md_real(tmp_path)
    stub = _Stub(tmp_path, str(md))

    MainWindow._on_mcp_prompt_requested(stub, dict(_PAYLOAD))  # type: ignore[arg-type]

    bruto = tel.jsonl_path().read_text(encoding="utf-8")
    assert str(md) not in bruto
    assert str(tmp_path) not in bruto
    # Fragmento: qualquer janela de 12 chars do prompt. Cobre truncagem em
    # qualquer offset, que e como um "so o comecinho para debugar" entra.
    limpo = "".join(ch for ch in _PROMPT_MARCADO if ch not in "\r\n")
    fragmentos = [
        limpo[i:i + 12] for i in range(0, len(limpo) - 12)
        if limpo[i:i + 12].strip()
    ]
    vazados = [f for f in fragmentos if f in bruto]
    assert vazados == [], f"fragmento do prompt no sidecar: {vazados[:3]}"
    # Hash tambem e o prompt: identifica o texto exato para quem tiver o
    # corpus, e a politica declarada e "nem truncado, nem hasheado".
    cru = _PROMPT_MARCADO.encode("utf-8")
    for algo in ("sha256", "sha1", "md5"):
        digest = hashlib.new(algo, cru).hexdigest()
        assert digest not in bruto, f"{algo} do prompt no sidecar"
        assert digest[:16] not in bruto, f"{algo} truncado do prompt no sidecar"
    (ev,) = _eventos()
    assert set(ev) <= set(tel.FIELD_ALLOWLIST)
    assert ev["prompt_chars"] == len(_PROMPT_MARCADO), (
        "o tamanho E o dado que substitui o texto: sem ele o teste acima "
        "passaria com o campo simplesmente ausente"
    )


# ---------------------------------------------------------------------------
# Comportamento: widget
# ---------------------------------------------------------------------------


def _espiao_de_emit(btn) -> list[dict]:
    """Payloads emitidos por `prompt_requested`.

    Gravar `click_blocked` e uma metade da afirmacao; a outra e que o
    clique NAO seguiu. Sem observar o `emit`, um gate que registrasse o
    bloqueio e despachasse assim mesmo passava por estes tres testes: o
    sidecar diria "bloqueado" enquanto o prompt ia para o terminal.
    """
    emitidos: list[dict] = []
    btn.prompt_requested.connect(lambda payload: emitidos.append(payload))
    return emitidos


def test_debounce_grava_click_blocked(
    qtbot, mcp_prompt_button_factory, codex_alive_factory, frozen_clock
):
    codex_alive_factory(True)
    _, btn = mcp_prompt_button_factory(button_type="Claude", action="Executar")
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert _reasons() == [], "o primeiro clique passa: nada bloqueado a registrar"
    emitidos = _espiao_de_emit(btn)

    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

    assert emitidos == [], "clique bloqueado nao pode ter sido despachado"
    (ev,) = _eventos()
    assert ev["event"] == tel.EVENT_CLICK_BLOCKED
    assert ev["reason"] == "debounced"
    assert ev["ok"] is False
    assert ev["action"] == "Executar"
    assert "resolved_provider" not in ev, (
        "o clique morreu antes do handler: nao houve resolucao de provider "
        "para gravar"
    )


def test_recusa_de_redisparo_grava_click_blocked(
    qtbot, mcp_prompt_button_factory, codex_alive_factory, frozen_clock, monkeypatch
):
    codex_alive_factory(True)
    _, btn = mcp_prompt_button_factory(button_type="Claude", action="Executar")
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    btn.mark_dispatch_result(True)
    frozen_clock(900)
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )
    emitidos = _espiao_de_emit(btn)

    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

    assert emitidos == [], "recusa de redisparo nao pode ter despachado"
    assert _reasons() == ["redispatch_declined"]


def test_codex_sem_t3_grava_click_blocked(
    qtbot, mcp_prompt_button_factory, codex_alive_factory
):
    """Botao Codex habilitado cujo T3 morreu entre o enable e o clique.

    Nao da para nascer com `codex_alive_factory(False)`: nesse caso o botao
    nasce `disabled` e o clique nunca chega ao slot. O gate em `_on_clicked`
    existe justamente para a janela em que o cache ja sabe que o T3 morreu e
    o `setEnabled` ainda nao foi reaplicado -- e e essa janela que o teste
    reproduz, envenenando so o cache.
    """
    codex_alive_factory(True)
    _, btn = mcp_prompt_button_factory(button_type="Codex", action="Executar")
    assert btn.isEnabled() is True
    btn._codex_alive_cache = False
    emitidos = _espiao_de_emit(btn)

    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

    assert emitidos == [], "Codex sem T3 nao pode ter despachado"
    (ev,) = _eventos()
    assert ev["reason"] == "codex_unavailable"
    assert ev["requested_provider"] == "Codex"


def test_clique_que_passa_nao_grava_bloqueio(
    qtbot, mcp_prompt_button_factory, codex_alive_factory
):
    """Controle: sem este, os tres testes acima passariam com o widget
    gravando um evento em TODO clique."""
    codex_alive_factory(True)
    _, btn = mcp_prompt_button_factory(button_type="Claude", action="Executar")
    recebidos: list[dict] = []
    btn.prompt_requested.connect(lambda p: recebidos.append(p))

    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

    assert len(recebidos) == 1
    assert _eventos() == []


# ---------------------------------------------------------------------------
# Achados da revisao R7 (codex-ultra, 2026-08-26)
# ---------------------------------------------------------------------------


def test_a_flag_de_reentrancia_sobe_colada_no_try_que_a_derruba():
    """R7 #14: quem levanta a flag e quem a abaixa precisam ser o mesmo bloco.

    A liberacao de `_prompt_in_flight` vive no `finally` do `try` do handler.
    Enquanto a flag subia antes das conversoes `str(...)` do payload, um caller
    programatico com um `__str__` que levanta escapava ANTES de existir `try`:
    a flag ficava verdadeira para sempre e todo botao do bloco morria ate o
    proximo restart do app.

    Gate estrutural em vez de comportamental porque o defeito nao tem sintoma
    observavel dentro de um teste -- ele so aparece no clique SEGUINTE, numa
    instancia de MainWindow que o teste ja descartou.
    """
    fn = _funcao(_MAIN_WINDOW_PY, "MainWindow", "_on_mcp_prompt_requested")
    subidas = [
        i for i, no in enumerate(fn.body)
        if isinstance(no, ast.Assign)
        and any(
            isinstance(alvo, ast.Attribute) and alvo.attr == "_prompt_in_flight"
            for alvo in no.targets
        )
    ]
    assert len(subidas) == 1, (
        "mais de um ponto levanta a flag no corpo do handler: so um pode, e "
        f"colado ao `try` (indices {subidas})"
    )
    i = subidas[0]
    assert i + 1 < len(fn.body) and isinstance(fn.body[i + 1], ast.Try), (
        "entre levantar a flag e o `try` que a derruba no `finally` nao pode "
        "haver nenhuma linha capaz de levantar"
    )


def test_degradacao_qwen_para_claude_e_gravada_como_claude(monkeypatch, tmp_path):
    """R7 #1: o provider gravado e o que EXECUTOU, nao o slug pedido.

    O roster do Main LLM (`queue-div-main-llm`) e superset do roster de
    brainstorm: qwen e grok nao tem persona aqui e degradam para Claude na
    resolucao. Enquanto `resolved_provider` recebia o slug cru, o evento dizia
    `resolved_provider="qwen"` num despacho que saiu inteiro por Claude --
    invertendo justamente a medicao que o par de campos existe para fazer.

    O teste antigo usava Kimi, um slug com persona de brainstorm (como MiMo)
    em que o cru e o resolvido coincidem, e por isso passava com o defeito no
    lugar.
    """
    _install_fakes(monkeypatch)
    stub = _Stub(tmp_path, str(_md_real(tmp_path)))
    stub._current_llm_provider = lambda: "qwen"  # type: ignore[assignment]
    payload = dict(_PAYLOAD, button_type="type-selector-radio-input")

    MainWindow._on_mcp_prompt_requested(stub, payload)  # type: ignore[arg-type]

    (ev,) = _eventos()
    assert ev["requested_provider"] == "type-selector-radio-input"
    assert ev["resolved_provider"] == "claude", (
        "qwen nao tem persona de brainstorm: o despacho foi por Claude e o "
        "registro precisa dizer Claude, senao a degradacao fica invisivel"
    )
    assert ev["terminal"] == 1, "T1 e o terminal de Claude: coerente com o registro"


def test_excecao_inesperada_registra_avisa_e_sobe(monkeypatch, tmp_path):
    """R7 #6: o `try` externo so tinha `finally`, e `finally` nao registra.

    Qualquer excecao fora do ValueError/TypeError de `build_prompt` terminava
    o handler sem evento, sem toast e sem `dispatch_result`: o sidecar ficava
    mudo exatamente no defeito que ninguem previu.
    """
    sinais = _install_fakes(monkeypatch)
    stub = _Stub(tmp_path, str(_md_real(tmp_path)))

    def _explode(_p: str) -> str:
        raise RuntimeError("topologia mudou")

    stub._rel_to_root = _explode  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="topologia mudou"):
        MainWindow._on_mcp_prompt_requested(stub, dict(_PAYLOAD))  # type: ignore[arg-type]

    assert _reasons() == ["handler_exception"]
    assert sinais.dispatch == [("mcp-prompt-btn-otimizar", False)], (
        "sem isto o botao de origem fica marcado como despachado apos um "
        "despacho que nunca aconteceu"
    )
    assert [lvl for _, lvl in sinais.toasts] == ["error"]


def test_criar_arquivo_nao_herda_o_artefato_do_picker(monkeypatch, tmp_path):
    """R7 #8: `artifact` era calculado antes de a action ser conhecida.

    O fluxo "Criar arquivo" define `md_ref=None` e ignora de proposito o `.md`
    ativo no picker. Herdar o hash dele fazia um sucesso de criacao aparecer
    atribuido a um arquivo que nao foi lido nem escrito.
    """
    _install_fakes(monkeypatch)
    stub = _Stub(tmp_path, str(_md_real(tmp_path)))
    payload = dict(_PAYLOAD, action="Criar arquivo", target_path_edit_inplace=False)

    MainWindow._on_mcp_prompt_requested(stub, payload)  # type: ignore[arg-type]

    (ev,) = _eventos()
    assert ev["reason"] == "ok"
    assert ev["artifact_id"] == "", (
        "o picker tinha um .md ativo, mas este fluxo nao o tocou: ausencia e "
        "a resposta correta, e ela precisa ser distinguivel de um hash"
    )


def test_codex_nascido_disabled_tambem_grava_o_bloqueio(
    qtbot, mcp_prompt_button_factory, codex_alive_factory
):
    """R7 #2: este e o caminho DOMINANTE de `codex_unavailable`.

    Quando o T3 ja esta ausente na construcao, o botao nasce `disabled`,
    `clicked` nunca chega ao slot e o clique morre no `eventFilter`. Instrumentar
    so o gate de `_on_clicked` cobria a janela rara (cache envenenado entre o
    enable e o clique) e deixava o caso comum contando como "botao nunca
    clicado" -- com o sinal invertido, porque um botao que o operador tenta
    usar e nao consegue apareceria como candidato a aposentadoria.
    """
    codex_alive_factory(False)
    _, btn = mcp_prompt_button_factory(
        button_type="Codex", action="Executar",
        target_path="terminal-codex-output",
    )
    assert btn.isEnabled() is False
    emitidos = _espiao_de_emit(btn)

    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

    assert emitidos == []
    (ev,) = _eventos()
    assert ev["event"] == tel.EVENT_CLICK_BLOCKED
    assert ev["reason"] == "codex_unavailable"
    assert ev["requested_provider"] == "Codex"
