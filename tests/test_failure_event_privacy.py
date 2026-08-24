"""Privacidade do FailureEvent (Task 14 / 13.1 linha Privacidade).

`_last_command` guarda a primeira linha inteira do que foi colado no terminal —
ate 500 chars, com args, flags, paths e o que mais estiver ali. Persistir isso
no corpus diario transformaria telemetria de falha em log de segredo.

O contrato e estreito de proposito: sai o NOME canonico do comando, ou nada.
Fragmento parcial seria pior que ausencia — contamina agregacao e ainda pode
carregar pedaco de segredo.
"""

from __future__ import annotations

import json
import re

import pytest

from workflow_app.telemetry.failure_event import (
    build_failure_event,
    sanitize_command_name,
)

# Amostras hostis: cada uma e uma forma real de segredo aparecer numa linha de
# terminal colada por um comando do pipeline.
LINHAS_SENSIVEIS = [
    "ANTHROPIC_API_KEY=sk-ant-api03-XXXXXXXXXXXX python3 run.py",
    "/home/pedro/Repositórios/systemForge/scripts/deploy.sh --prod",
    "curl -H 'Authorization: Bearer ghp_ABCDEFGHIJKLMNOP' https://api.github.com",
    "psql postgres://user:senha123@db.internal:5432/prod",
    "ssh -i ~/.ssh/id_ed25519 root@203.0.113.10",
    "export SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiJ9.payload.sig",
    "--token=abc123 --project /home/pedro/secreto",
    "cat <<'EOF' > /etc/shadow.bak",
    'echo "senha: hunter2" >> notas.txt',
    "~/bin/rotate-creds.sh --key AKIAIOSFODNN7EXAMPLE",
]

# Padroes que NUNCA podem aparecer no campo persistido.
_PROIBIDOS = [
    re.compile(r"sk-ant-", re.I),
    re.compile(r"ghp_[A-Za-z0-9]"),
    re.compile(r"AKIA[0-9A-Z]{8}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{5,}"),
    re.compile(r"senha|password|secret|token|api[_-]?key", re.I),
    re.compile(r"Bearer\s", re.I),
    re.compile(r"/home/|/etc/|/root/|~/"),
    re.compile(r"://"),
    re.compile(r"--\w"),
    re.compile(r"[<>|\"']"),
    re.compile(r"="),
]


def _assert_limpo(valor):
    if valor is None:
        return
    for padrao in _PROIBIDOS:
        assert not padrao.search(valor), f"vazamento ({padrao.pattern}) em {valor!r}"


class TestSanitizacaoDeComando:
    @pytest.mark.parametrize("linha", LINHAS_SENSIVEIS)
    def test_linha_hostil_nao_vaza_nada(self, linha):
        _assert_limpo(sanitize_command_name(linha))

    @pytest.mark.parametrize("linha", LINHAS_SENSIVEIS)
    def test_linha_hostil_nao_vaza_pelo_evento_serializado(self, linha):
        ev = build_failure_event(
            channel="workspace", reason="EXIT_NONZERO", raw_command=linha
        )
        _assert_limpo(ev["command_name"])
        serializado = json.dumps(ev, ensure_ascii=False)
        for fragmento in ("sk-ant-", "ghp_", "AKIA", "hunter2", "senha123", "/home/pedro"):
            assert fragmento not in serializado, f"{fragmento} vazou no evento"

    def test_env_inline_nao_vira_nome_de_comando(self):
        # `VAR=valor cmd` — o head token E o segredo. Recusar e a unica saida.
        assert sanitize_command_name("ANTHROPIC_API_KEY=sk-ant-1 python3 x.py") is None

    def test_path_absoluto_nao_e_confundido_com_slash_command(self):
        # Comeca com barra, como um slash-command, mas e path: duas barras.
        assert sanitize_command_name("/home/pedro/deploy.sh --prod") is None
        assert sanitize_command_name("/usr/bin/env") is None

    def test_flag_solta_nao_vira_nome(self):
        assert sanitize_command_name("--token=abc123") is None
        assert sanitize_command_name("-rf /") is None

    def test_redirecionamento_e_heredoc_nao_viram_nome(self):
        for linha in ("<<'EOF'", "> /etc/passwd", "| tee log.txt", "$SECRET"):
            assert sanitize_command_name(linha) is None


class TestPreservacaoDoQueImporta:
    """Sanitizar demais e tao ruim quanto de menos: sem `command_name` o funil
    volta a nao dizer O QUE falhou."""

    @pytest.mark.parametrize(
        "linha,esperado",
        [
            ("/loop:iteraction:execute-task --item 013", "/loop:iteraction:execute-task"),
            ("/mcp:codex-ultra", "/mcp:codex-ultra"),
            ("/build-module-pipeline --module 4", "/build-module-pipeline"),
            ("/qa:trace  --module 2", "/qa:trace"),
            ("pytest tests/ -q --no-cov", "pytest"),
            ("npm run build", "npm"),
            ("python3 script.py --flag", "python3"),
        ],
    )
    def test_nome_canonico_sobrevive(self, linha, esperado):
        assert sanitize_command_name(linha) == esperado

    def test_args_nunca_acompanham_o_nome(self):
        nome = sanitize_command_name("/execute-task --module 3 --task 7")
        assert nome == "/execute-task"
        assert "--" not in nome
        assert "3" not in nome

    def test_apenas_a_primeira_linha_e_considerada(self):
        colado = "/commit:simple --module 1\nGITHUB_TOKEN=ghp_XXXXXXXXXXXX git push\n"
        nome = sanitize_command_name(colado)
        assert nome == "/commit:simple"
        _assert_limpo(nome)

    def test_nome_tem_tamanho_limitado(self):
        # 500 chars de `_last_command` nao podem atravessar inteiros.
        gigante = "/" + "a" * 4000
        assert sanitize_command_name(gigante) is None
        assert sanitize_command_name("x" * 4000) is None


class TestIntegracaoComOEmissor:
    def test_emissor_do_metrics_bar_passa_pelo_sanitizador(self):
        from pathlib import Path

        fonte = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "workflow_app"
            / "metrics_bar"
            / "metrics_bar.py"
        ).read_text(encoding="utf-8")
        trecho = fonte[fonte.index("def _append_failure_telemetry") :]
        trecho = trecho[: trecho.index("def _schedule_recovery_prompt")]
        # O envelope tem que ser montado pelo construtor versionado, nao inline.
        assert "build_failure_event" in trecho
        # E o comando bruto so pode entrar por `raw_command`, que sanitiza.
        assert "raw_command=self._last_command.get(channel)" in trecho
        assert '"command": self._last_command' not in trecho

    def test_nenhum_campo_do_evento_contem_o_texto_bruto(self):
        bruto = "GITHUB_TOKEN=ghp_SEGREDO /commit:simple --module 1"
        ev = build_failure_event(
            channel="interactive",
            reason="BLOCKED",
            raw_command=bruto,
            run_id="run-1",
            item_id="007",
        )
        for chave, valor in ev.items():
            if isinstance(valor, str):
                assert "ghp_SEGREDO" not in valor, f"segredo em {chave}"
                assert bruto not in valor, f"linha bruta em {chave}"
