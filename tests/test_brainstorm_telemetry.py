"""Gate do sidecar de telemetria do bloco brainstorm-mcp (C4, Tasks 34 e 37).

Tres invariantes carregam o peso:

1. **Allowlist fechada.** Nenhuma chave fora de `FIELD_ALLOWLIST` chega ao
   disco, e a tentativa LEVANTA em modo estrito.
2. **Zero vazamento.** Nenhum VALOR gravado casa padrao de segredo ou de path
   absoluto -- verificado parseando cada linha do JSONL, nunca com `grep -c`
   sobre nome de chave (com zero matches o `grep` imprime `0` e sai `1`, e um
   path absoluto gravado sob a chave `artifact_id` passaria limpo).
3. **Paridade MEDIDA com o hook de segredos**, em vez de herdada por comentario.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from pathlib import Path

import pytest

from workflow_app import brainstorm_telemetry as tel

REPO_ROOT = Path(__file__).parents[3].resolve()
HOOK = REPO_ROOT / ".claude" / "hooks" / "pretool-bash-secrets.sh"


@pytest.fixture(autouse=True)
def _sidecar_isolado(tmp_path, monkeypatch):
    """Redireciona o sidecar e restaura TODO o estado global do modulo.

    `_reset_for_tests` muta globais do modulo; sem restauracao, um teste
    contamina o proximo e o modo estrito vaza para o resto da suite.
    """
    antes = (
        tel._LOG_DIR, tel._JSONL_PATH, tel._strict, tel._seq,
        tel._writer_disabled,
    )
    tel._reset_for_tests(log_dir=tmp_path / "logs", strict=True)
    yield tmp_path / "logs"
    (
        tel._LOG_DIR, tel._JSONL_PATH, tel._strict, tel._seq,
        tel._writer_disabled,
    ) = antes


def _linhas() -> list[dict]:
    path = tel.jsonl_path()
    if not path.exists():
        return []
    return [
        json.loads(linha)
        for linha in path.read_text(encoding="utf-8").splitlines()
        if linha.strip()
    ]


# ---------------------------------------------------------------------------
# 1. Forma do registro
# ---------------------------------------------------------------------------


def test_schema_version_e_o_declarado_no_plano():
    assert tel.SCHEMA_VERSION == "brainstorm-mcp-dispatch/1"


def test_um_evento_produz_exatamente_uma_linha_jsonl_valida():
    tel.record_dispatch(reason="ok", testid_slug="criar-md", terminal=1)
    linhas = _linhas()
    assert len(linhas) == 1
    reg = linhas[0]
    assert reg["schema"] == tel.SCHEMA_VERSION
    assert reg["event"] == tel.EVENT_DISPATCH
    assert reg["reason"] == "ok"
    assert reg["ok"] is True


def test_dispatch_id_e_pid_traco_seq_e_a_seq_e_monotonica():
    """Formato `{pid}-{seq}`. A limitacao (PID reciclado, `_seq` reinicia)
    esta declarada na docstring do modulo; aqui so o formato e a monotonia."""
    tel.record_dispatch(reason="ok")
    tel.record_dispatch(reason="in_flight")
    ids = [reg["dispatch_id"] for reg in _linhas()]
    assert ids == [f"{tel.os.getpid()}-1", f"{tel.os.getpid()}-2"]
    assert [reg["seq"] for reg in _linhas()] == [1, 2]


def test_disco_indisponivel_nao_levanta_ao_chamador(tmp_path):
    """`OSError` no sidecar e engolido: telemetria nunca derruba o dispatch."""
    bloqueio = tmp_path / "arquivo-no-lugar-do-dir"
    bloqueio.write_text("nao sou diretorio", encoding="utf-8")
    tel._reset_for_tests(log_dir=bloqueio / "logs", strict=True)
    # Nao levanta, mesmo em modo estrito: estrito julga CONTRATO (allowlist,
    # reason), nunca disponibilidade de disco.
    tel.record_dispatch(reason="ok")
    assert not tel.jsonl_path().exists()


# ---------------------------------------------------------------------------
# 2. Allowlist fechada
# ---------------------------------------------------------------------------


def test_campo_fora_da_allowlist_levanta_em_modo_estrito():
    with pytest.raises(ValueError, match="fora da allowlist"):
        tel._emit_record(tel.EVENT_DISPATCH, "ok", {"campo_inventado": "x"})
    assert _linhas() == []


def test_campo_fora_da_allowlist_e_descartado_em_producao():
    """Producao nao levanta: um campo novo mal instrumentado nao pode derrubar
    o clique do operador. Ele some da linha, e o resto do evento sobrevive."""
    tel._reset_for_tests(log_dir=tel._LOG_DIR, strict=False)
    tel._emit_record(tel.EVENT_DISPATCH, "ok", {"campo_inventado": "x", "terminal": 2})
    linhas = _linhas()
    assert len(linhas) == 1
    assert "campo_inventado" not in linhas[0]
    assert linhas[0]["terminal"] == 2


def test_valor_composto_e_recusado():
    """Nenhum campo da allowlist e dict/list; aceitar composto abriria caminho
    para carregar por dentro o que a allowlist barra por fora."""
    with pytest.raises(ValueError, match="nao escalar"):
        tel._emit_record(tel.EVENT_DISPATCH, "ok", {"action": {"a": 1}})


def test_o_prompt_nao_tem_campo_para_entrar():
    """Estrutural, e nao "ninguem passou ainda": as duas chaves que carregam
    texto de prompt no payload do botao nao existem na allowlist, entao nao ha
    caminho por onde o prompt entre."""
    assert "prompt" not in tel.FIELD_ALLOWLIST
    assert "prompt_text" not in tel.FIELD_ALLOWLIST
    assert "action_literal" not in tel.FIELD_ALLOWLIST
    with pytest.raises(ValueError, match="fora da allowlist"):
        tel._emit_record(tel.EVENT_DISPATCH, "ok", {"prompt_text": "corpo inteiro"})


def test_o_prompt_nao_persiste_inteiro_por_um_campo_legitimo():
    """A allowlist fecha NOMES; ela nao sabe o que ha dentro do valor.

    O vetor real de vazamento nunca foi uma chave `prompt` -- essa a
    allowlist barra -- e sim o corpo do prompt depositado num campo que a
    allowlist aceita, como `action`. A regra que fecha isso e nitida e nao
    depende de classificar prosa: NENHUM campo permitido e legitimamente
    multilinha, e prompt de brainstorm sempre tem quebra de linha.
    """
    prompt = "## Prompt canonico\nleia o arquivo\nresponda em pt-BR\n"
    tel._emit_record(tel.EVENT_DISPATCH, "ok", {"action": prompt})

    gravado = _linhas()[0]["action"]
    assert "\n" not in gravado
    assert "responda em pt-BR" not in gravado, (
        "o corpo do prompt persistiu inteiro por um campo da allowlist"
    )
    assert gravado.endswith("...(+multilinha)")


def test_toda_chave_gravada_pertence_a_allowlist():
    """Parseia cada linha; conjunto de chaves contido na allowlist."""
    tel.record_dispatch(
        reason="ok",
        button_id="mcp-prompt-btn-criar-md",
        testid_slug="criar-md",
        action="Criar arquivo",
        requested_provider="type-selector-radio-input",
        resolved_provider="Claude",
        source_kind="seed",
        artifact="deadbeefdeadbeef",
        terminal=1,
        prompt_chars=4096,
    )
    tel.record_click_blocked(reason="debounced", testid_slug="pesquisar")
    linhas = _linhas()
    assert linhas
    for reg in linhas:
        fora = set(reg) - tel.FIELD_ALLOWLIST
        assert not fora, f"chaves fora da allowlist gravadas: {sorted(fora)}"


# ---------------------------------------------------------------------------
# 3. Conjunto fechado de `reason`
# ---------------------------------------------------------------------------


def test_reason_desconhecido_levanta():
    with pytest.raises(ValueError, match="nao pertence ao evento"):
        tel.record_dispatch(reason="motivo-que-nao-existe")


def test_reason_de_widget_nao_passa_como_dispatch_e_vice_versa():
    """Os dois conjuntos sao disjuntos e cada evento so aceita o seu.

    Sem isso, `debounced` gravado como `dispatch` faria o agregador contar um
    despacho que nunca houve -- exatamente o oposto do dado que C4 quer."""
    assert not (tel.HANDLER_REASONS & tel.WIDGET_REASONS)
    with pytest.raises(ValueError, match="nao pertence ao evento"):
        tel.record_dispatch(reason="debounced")
    with pytest.raises(ValueError, match="nao pertence ao evento"):
        tel.record_click_blocked(reason="ok")


def test_todos_os_reasons_fechados_sao_gravaveis():
    """Cobertura no nivel do MODULO: nenhum `reason` declarado e inalcancavel
    por construcao (typo no conjunto, evento errado).

    Isto NAO prova que o handler alcanca cada caminho -- essa prova e do
    `test_brainstorm_telemetry_instrumentation.py`, que exercita o codigo real.
    """
    for motivo in sorted(tel.HANDLER_REASONS):
        tel.record_dispatch(reason=motivo)
    for motivo in sorted(tel.WIDGET_REASONS):
        tel.record_click_blocked(reason=motivo)
    vistos = {reg["reason"] for reg in _linhas()}
    assert vistos == tel.HANDLER_REASONS | tel.WIDGET_REASONS


def test_ok_e_derivado_do_reason_e_nao_passado_pelo_chamador():
    tel.record_dispatch(reason="ok")
    tel.record_dispatch(reason="publish_failed")
    assert [reg["ok"] for reg in _linhas()] == [True, False]


# ---------------------------------------------------------------------------
# 4. Zero vazamento -- por VALOR, nunca por nome de chave
# ---------------------------------------------------------------------------

#: Padroes que NENHUM valor gravado pode casar. Deliberadamente independentes
#: dos padroes do modulo: se o teste reusasse `tel._SECRET_PATTERNS`, ele
#: provaria apenas que o modulo e coerente consigo mesmo.
_PROIBIDOS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("path absoluto posix", re.compile(r"(?<![A-Za-z0-9_*])/[A-Za-z0-9_.-]+/")),
    ("path absoluto windows", re.compile(r"[A-Za-z]:\\")),
    ("home do usuario", re.compile(r"(?i)/home/|/Users/")),
    ("chave sk", re.compile(r"sk-[A-Za-z0-9_-]{16,}")),
    ("token de provider", re.compile(r"\b(?:sbp_|ghp_|ghs_|vcp_|rly_)[A-Za-z0-9]{10,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.")),
    ("bearer", re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{12,}")),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("password inline", re.compile(r"(?i)password=[^\s'\"]{8,}")),
    # Os cinco abaixo fecham o buraco apontado pela revisao R7 #4: o
    # catalogo so reconhecia segredo de prefixo famoso (`sk-`, `ghp_`).
    # Um `TAVILY_API_KEY=tvly-...` ou um token hex de 40 chars atravessava
    # o gate inteiro, e o teste passava com o vazamento no disco.
    ("credencial nomeada", re.compile(
        r"(?i)\b[a-z0-9_.-]*(?:api[_-]?key|access[_-]?key|secret[_-]?key"
        r"|auth[_-]?token|api[_-]?token|credential)[a-z0-9_.-]*\s*[=:]\s*"
        r"[^\s'\"]{8,}"
    )),
    ("token hex longo", re.compile(r"\b[A-Fa-f0-9]{32,}\b")),
    # Um path absoluto de UM componente (`/segredo`) nao tem barra interna
    # e escapava de todo padrao de path do catalogo.
    ("path absoluto posix", re.compile(r"(?<![\w.])/[A-Za-z0-9._-]+")),
    ("path absoluto windows", re.compile(r"(?i)\b[a-z]:[\\/]")),
    ("multilinha", re.compile(r"[\r\n]")),
)


def test_nenhum_valor_gravado_casa_padrao_de_segredo_ou_de_path_absoluto():
    """O chamador tenta vazar em TODO campo string da allowlist; nada passa."""
    veneno = (
        "/home/pedro/Repositorios/systemForge/blacksmith/nota.md "
        "sk-ant-api03-" + "A" * 90 + " ghp_" + "B" * 36 +
        " Bearer abcdefghijklmnop forjasistemas.suporte@gmail.com "
        "password=supersecreta C:\\Users\\pedro\\segredo.txt "
        # R7 #4: as quatro classes que o catalogo antigo nao via.
        "TAVILY_API_KEY=tvly-dev-abcdefgh12345678 "
        "twilio " + "9f" * 20 + " /segredo\n"
        "segunda linha com o resto do prompt colado"
    )
    tel.record_dispatch(
        reason="ok",
        button_id=veneno,
        testid_slug=veneno,
        action=veneno,
        requested_provider=veneno,
        resolved_provider=veneno,
        source_kind=veneno,
        artifact=veneno,
    )
    tel.record_click_blocked(reason="debounced", button_id=veneno, action=veneno)
    linhas = _linhas()
    assert linhas
    achados = []
    for reg in linhas:
        for chave, valor in reg.items():
            if not isinstance(valor, str):
                continue
            for rotulo, padrao in _PROIBIDOS:
                if padrao.search(valor):
                    achados.append(f"  {chave}={valor!r} casou {rotulo}")
    assert not achados, "vazamento no sidecar:\n" + "\n".join(achados)


def test_o_scrub_acontece_no_escritor_e_nao_no_chamador():
    """Um chamador futuro que esqueca de mascarar continua coberto."""
    tel._emit_record(tel.EVENT_DISPATCH, "ok", {"action": "/home/pedro/x.md"})
    assert _linhas()[0]["action"] == "***path***"


# ---------------------------------------------------------------------------
# 5. Paridade com `pretool-bash-secrets.sh`: MEDIDA, nao herdada
# ---------------------------------------------------------------------------


def _classes_do_hook() -> dict[str, str]:
    """Extrai `SECRET_PATTERNS` do hook por AST do Python embutido no shell.

    O hook e um `.sh` com um heredoc Python dentro. Parsear o literal da lista
    por AST evita reimplementar a leitura como regex sobre shell, que quebraria
    na primeira reformatacao do arquivo.
    """
    texto = HOOK.read_text(encoding="utf-8")
    # O fim da lista e o `]` sozinho no inicio de uma linha. Procurar o
    # primeiro `]` a partir do inicio acharia o fecho da classe de caracteres
    # `[A-Za-z0-9_-]` do primeiro padrao e truncaria o literal no meio.
    m = re.search(
        r"^SECRET_PATTERNS = (\[.*?^\])$", texto, re.MULTILINE | re.DOTALL
    )
    assert m, "SECRET_PATTERNS nao encontrado no hook; o formato mudou"
    lista = ast.literal_eval(m.group(1))
    return {rotulo: padrao for padrao, rotulo, _sev in lista}


@pytest.mark.skipif(not HOOK.exists(), reason="hook de segredos ausente no repo")
def test_toda_classe_do_hook_de_segredos_e_mascarada_aqui():
    """Anti-drift do defeito que C4 mandou nao herdar.

    `dispatch_telemetry.py:46-57` afirma cobrir "as mesmas classes que
    `pretool-bash-secrets.sh` bloqueia" e nao cobre: das 13 classes do hook,
    faltam `sbp_`, `ghp_`, `ghs_`, `vcp_`, `rly_`, `Authorization: Bearer`,
    `password=` e `secret=`. Este teste transforma a afirmacao em gate: uma
    classe nova no hook deixa este teste VERMELHO ate ser coberta aqui.

    A amostra e gerada a partir do proprio padrao do hook, entao o teste nao
    carrega uma segunda copia das classes.
    """
    amostras = {
        "anthropic-api-key": "sk-ant-api03-" + "A" * 90,
        "openai-sk-proj": "sk-proj-" + "A" * 45,
        "openai-api-key": "sk-" + "A" * 45,
        "supabase-pat": "sbp_" + "a" * 40,
        "github-pat": "ghp_" + "A" * 36,
        "github-app-secret": "ghs_" + "A" * 36,
        "vercel-token": "vcp_" + "A" * 30,
        "railway-pat": "rly_" + "A" * 20,
        "jwt": "eyJ" + "A" * 30 + "." + "B" * 12 + "." + "C" * 12,
        "bearer-token-inline": "Bearer " + "A" * 32,
        "auth-header": "Authorization: Bearer " + "A" * 24,
        "password-inline": "password=trocaisso123",
        "secret-inline": "secret=trocaisso123",
    }
    classes = _classes_do_hook()
    faltando_amostra = sorted(set(classes) - set(amostras))
    assert not faltando_amostra, (
        "o hook ganhou classe(s) de segredo sem amostra neste teste: "
        f"{faltando_amostra}. Acrescente a amostra E o padrao correspondente "
        "em `brainstorm_telemetry._SECRET_PATTERNS`."
    )
    nao_mascaradas = []
    for rotulo, padrao_hook in classes.items():
        amostra = amostras[rotulo]
        assert re.search(padrao_hook, amostra), (
            f"amostra de {rotulo} nao casa o proprio padrao do hook; "
            "a amostra esta errada, nao o modulo"
        )
        if amostra in tel.scrub(f"valor {amostra} fim"):
            nao_mascaradas.append(rotulo)
    assert not nao_mascaradas, (
        "classes bloqueadas pelo hook e NAO mascaradas por "
        f"brainstorm_telemetry.scrub: {sorted(nao_mascaradas)}"
    )


def test_o_modulo_nao_herda_a_promessa_de_paridade_do_precedente():
    """O docstring precisa dizer que a paridade foi MEDIDA e e falsa no
    precedente. Sem isso a proxima leitura reintroduz a herança silenciosa."""
    doc = tel.__doc__ or ""
    assert "pretool-bash-secrets.sh" in doc
    assert "medida" in doc.lower() or "verificada" in doc.lower()


# ---------------------------------------------------------------------------
# 6. `artifact_id` e `source_kind`
# ---------------------------------------------------------------------------


def test_artifact_id_e_hash_estavel_do_path_relativo(tmp_path):
    raiz = tmp_path / "repo"
    (raiz / "blacksmith").mkdir(parents=True)
    alvo = raiz / "blacksmith" / "nota.md"
    alvo.write_text("x", encoding="utf-8")
    a = tel.artifact_id(alvo, raiz)
    b = tel.artifact_id(str(alvo), str(raiz))
    assert a == b
    assert re.fullmatch(r"[0-9a-f]{16}", a)
    assert "nota" not in a and "blacksmith" not in a


def test_artifact_id_muda_quando_o_path_relativo_muda(tmp_path):
    raiz = tmp_path / "repo"
    (raiz / "a").mkdir(parents=True)
    (raiz / "b").mkdir(parents=True)
    (raiz / "a" / "n.md").write_text("x", encoding="utf-8")
    (raiz / "b" / "n.md").write_text("x", encoding="utf-8")
    assert tel.artifact_id(raiz / "a" / "n.md", raiz) != tel.artifact_id(
        raiz / "b" / "n.md", raiz
    )


def test_artifact_id_vazio_para_ausencia_e_para_fora_do_root(tmp_path):
    """Ausencia e um dado legitimo e nao pode virar hash de string vazia, que
    pareceria um artefato real. Fora do root tambem: o relativo seria uma
    escada de `..` carregando a topologia da maquina."""
    raiz = tmp_path / "repo"
    raiz.mkdir()
    assert tel.artifact_id(None, raiz) == ""
    assert tel.artifact_id("", raiz) == ""
    assert tel.artifact_id(raiz / "x.md", None) == ""
    fora = tmp_path / "fora.md"
    fora.write_text("x", encoding="utf-8")
    assert tel.artifact_id(fora, raiz) == ""


def test_source_kind_le_os_dois_diretorios_do_contrato(tmp_path):
    from workflow_app.brainstorm_seed_contract import (
        BRAINSTORM_SEEDS_RELDIR,
        SUPPLEMENTAL_SEEDS_RELDIR,
    )

    raiz = tmp_path / "repo"
    seeds = raiz / BRAINSTORM_SEEDS_RELDIR
    supl = raiz / SUPPLEMENTAL_SEEDS_RELDIR
    seeds.mkdir(parents=True)
    supl.mkdir(parents=True)
    (seeds / "01-criar-md.md").write_text("x", encoding="utf-8")
    (supl / "search-prod.md").write_text("x", encoding="utf-8")
    assert tel.source_kind_for(seeds / "01-criar-md.md", raiz) == "seed"
    assert tel.source_kind_for(supl / "search-prod.md", raiz) == "supplemental"
    assert tel.source_kind_for(raiz / "outro.md", raiz) == "unknown"
    assert tel.source_kind_for(None, raiz) == "unknown"


def test_supplemental_vence_seed_por_estar_aninhado(tmp_path):
    """`seeds/supplemental/` esta DENTRO de `seeds/`: a ordem dos testes no
    resolvedor e o que impede o suplemento de ser classificado como seed."""
    from workflow_app.brainstorm_seed_contract import SUPPLEMENTAL_SEEDS_RELDIR

    raiz = tmp_path / "repo"
    supl = raiz / SUPPLEMENTAL_SEEDS_RELDIR
    supl.mkdir(parents=True)
    alvo = supl / "search-prod.md"
    alvo.write_text("x", encoding="utf-8")
    assert tel.source_kind_for(alvo, raiz) == "supplemental"


# ---------------------------------------------------------------------------
# Guarda de suite: a telemetria de teste nao vaza para o sidecar do operador
# ---------------------------------------------------------------------------


def test_a_guarda_esta_armada_pelo_conftest():
    assert os.environ.get(tel.GUARD_ENV) == "1"


def test_a_guarda_veda_o_diretorio_real_e_libera_o_tmp(tmp_path):
    """So o diretorio real e vedado.

    Vedar tudo faria esta propria suite -- que precisa ler o que escreveu --
    perder a capacidade de se testar, e a guarda seria removida no primeiro
    teste novo que precisasse do sidecar.
    """
    assert tel.real_sidecar_blocked(tel._DEFAULT_LOG_DIR) is True
    assert tel.real_sidecar_blocked(tmp_path) is False
    assert tel.real_sidecar_blocked(None) is False


def test_emitir_com_o_caminho_real_nao_toca_o_disco_do_operador(monkeypatch):
    """Sem monkeypatch de path: o diretorio real fica byte a byte igual.

    Espelha `test_telemetry_no_real_write.py`. A licao ja foi paga uma vez:
    760 dos 2.553 eventos do corte auditado de `.claude/wf-failures/` eram
    ruido de pytest. Os pontos de termino do brainstorm agora emitem em
    toda construcao de MainWindow da suite -- sem esta guarda, o sidecar do
    operador viraria o mesmo lixo.
    """
    real = tel._DEFAULT_LOG_DIR

    def _instantaneo():
        """Nome+tamanho nao bastava (R7 #10).

        Ele nao via (a) o diretorio sendo CRIADO -- ausente e `{}`, recem
        criado e vazio tambem e `{}` -- nem (b) uma sobrescrita de mesmo
        numero de bytes. `None` para ausencia separa (a); `mtime_ns` mais o
        sha256 da cauda separa (b) sem pagar hash do arquivo inteiro, que
        no sidecar de um operador de verdade pode ter dezenas de MB.
        """
        if not real.is_dir():
            return None
        estado = {}
        for item in sorted(real.iterdir()):
            if not item.is_file():
                continue
            st = item.stat()
            with item.open("rb") as fh:
                if st.st_size > 8192:
                    fh.seek(-8192, os.SEEK_END)
                cauda = fh.read()
            estado[item.name] = (
                st.st_size, st.st_mtime_ns, hashlib.sha256(cauda).hexdigest()
            )
        return estado

    antes = _instantaneo()
    tel._reset_for_tests(log_dir=real, strict=True)
    registro = tel.record_dispatch(reason="ok", button_id="b", testid_slug="s")

    assert _instantaneo() == antes, "a suite escreveu no sidecar real"
    if antes is None:
        assert not real.exists(), "a guarda suprimiu o byte mas criou o diretorio"
    # A validacao continua rodando: e o byte no disco que se suprime, nao a
    # checagem que faz o gate valer.
    assert registro["reason"] == "ok"
    assert set(registro) <= set(tel.FIELD_ALLOWLIST)


def test_com_a_guarda_baixada_o_caminho_real_voltaria_a_escrever(monkeypatch, tmp_path):
    """Controle: prova que o teste acima mede a guarda, e nao um no-op.

    Sem ele, um `_write_jsonl` quebrado (que nunca escreve em lugar nenhum)
    passaria pelo teste anterior como se a guarda estivesse funcionando.
    """
    monkeypatch.delenv(tel.GUARD_ENV, raising=False)
    falso_real = tmp_path / "home-falso" / "logs"
    monkeypatch.setattr(tel, "_DEFAULT_LOG_DIR", falso_real)
    tel._reset_for_tests(log_dir=falso_real, strict=True)

    assert tel.real_sidecar_blocked(falso_real) is False
    tel.record_dispatch(reason="ok", button_id="b")
    assert tel.jsonl_path().is_file()
    assert tel.jsonl_path().read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# Achados da revisao R7 (codex-ultra, 2026-08-26)
# ---------------------------------------------------------------------------


def test_a_guarda_julga_o_diretorio_que_o_escritor_de_fato_abre(monkeypatch, tmp_path):
    """R7 #9: a guarda lia `_LOG_DIR`, o `open` usava `_JSONL_PATH`.

    Sao dois globais. Bastava um caller atualizar so um -- e `_reset_for_tests`
    nao e o unico caminho ate eles -- para a guarda aprovar um `tmp_path` e o
    byte cair no home real. Aqui a divergencia e montada de proposito.
    """
    real = tmp_path / "home-falso" / "logs"
    monkeypatch.setattr(tel, "_DEFAULT_LOG_DIR", real)
    monkeypatch.setenv(tel.GUARD_ENV, "1")
    monkeypatch.setattr(tel, "_LOG_DIR", tmp_path / "logs-liberado")
    monkeypatch.setattr(tel, "_JSONL_PATH", real / "dispatch.jsonl")

    tel.record_dispatch(reason="ok", button_id="b")

    assert not real.exists(), (
        "a guarda aprovou o diretorio global e o escritor abriu outro"
    )


def test_a_guarda_nao_e_comparacao_lexical_de_string(monkeypatch, tmp_path):
    """R7 #9: `.../logs/../logs` e `.../logs` sao o mesmo diretorio.

    Comparando texto, o primeiro passava pela guarda e escrevia no segundo.
    """
    real = tmp_path / "home-falso" / "logs"
    real.mkdir(parents=True)
    monkeypatch.setattr(tel, "_DEFAULT_LOG_DIR", real)
    monkeypatch.setenv(tel.GUARD_ENV, "1")

    disfarce = real / ".." / "logs"
    assert str(disfarce) != str(real)
    assert tel.real_sidecar_blocked(disfarce) is True


def test_escrita_lenta_desliga_o_sidecar_em_vez_de_esticar_o_dispatch(monkeypatch):
    """R7 #13: a escrita e sincrona na thread da UI, dentro do clique.

    O `finally` do handler so agenda a liberacao de `_prompt_in_flight` depois
    que ela retorna: telemetria lenta faz o proprio bloco classificar cliques
    legitimos como `in_flight`, fabricando o evento que existe para medir. O
    disjuntor troca telemetria (dano menor) por dispatch livre (dano maior).
    """
    monkeypatch.setattr(tel, "_SLOW_WRITE_SECONDS", -1.0)  # toda escrita "estoura"

    tel.record_dispatch(reason="ok", button_id="primeira")
    assert tel._writer_disabled is True
    assert len(_linhas()) == 1, "a escrita que estourou o teto ainda persiste"

    tel.record_dispatch(reason="ok", button_id="segunda")
    assert len(_linhas()) == 1, "sidecar desligado continuou escrevendo"


def test_o_mesmo_path_relativo_sob_raizes_diferentes_da_o_mesmo_hash(tmp_path):
    """R7 #11: o teste antigo so exercitava UMA raiz.

    Ele provava que o hash e estavel e que `str` e `Path` coincidem -- nao que
    o insumo e o path RELATIVO. Um `artifact_id` que hasheasse o absoluto
    passava por ele inteiro, e a topologia da maquina (nome de usuario,
    diretorio de checkout) viraria a chave de agrupamento do sidecar.
    """
    a, b = tmp_path / "clone-a", tmp_path / "clone-b"
    for raiz in (a, b):
        (raiz / "blacksmith").mkdir(parents=True)
        (raiz / "blacksmith" / "nota.md").write_text("x", encoding="utf-8")

    assert tel.artifact_id(a / "blacksmith" / "nota.md", a) == tel.artifact_id(
        b / "blacksmith" / "nota.md", b
    )


def test_o_reason_de_excecao_inesperada_esta_no_vocabulario():
    """R7 #6: o handler passou a registrar antes de relevantar.

    Sem a entrada aqui, o modo estrito da suite transformaria o registro do
    defeito num segundo defeito, e a producao descartaria o evento calada --
    exatamente o silencio que o achado pediu para fechar.
    """
    assert "handler_exception" in tel.HANDLER_REASONS
    tel.record_dispatch(reason="handler_exception", button_id="b")
    assert _linhas()[0]["reason"] == "handler_exception"
