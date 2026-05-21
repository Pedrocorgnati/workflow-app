# DCP Matrix Canonical Checklist

Origem: `ai-forge/workflow-app/docs/DCP-MATRIX-CANONICAL-TASKLIST.md`
Data: 2026-05-19

## Execucao

- [x] Alinhar enums do modelo Pydantic da matrix.
  - `PhaseLiteral` aceita `B-tdd` e `B-dcp`.
  - `ModelLiteral` aceita `sonnet`.
  - `EffortLiteral` aceita `max`.
  - `InteractionLiteral` aceita `manual`, `auto` e `inter` alem de `interactive/headless`.
  - `TrailGateLiteral` aceita `load-queue`.

- [x] Alinhar enums runtime do workflow-app.
  - `ModelName` e `ModelType` agora incluem `SONNET`.
  - Loaders DCP mapeiam `sonnet` para `ModelName.SONNET`, nao para `SONNET`.
  - Badges, dialogs e template builder reconhecem `Sonnet` para evitar `KeyError` na renderizacao Qt.

- [x] Fazer `DCP-COMMAND-MATRIX.json` ser o caminho canonico do botao `DCP: Specific-Flow`.
  - `_on_dcp_specific_flow_clicked` tenta matrix primeiro.
  - `_handle_dcp_load_specific_flow` tenta matrix primeiro apos a pipeline B-dcp.
  - `SPECIFIC-FLOW.json` ficou como fallback legacy quando a matrix esta ausente/invalida.

- [x] Renderizar lista sequencial com diretivas como linhas separadas.
  - `derive_queue_from_matrix(..., include_directives=True)` injeta `/clear`, `/model`, `/effort` como `CommandSpec` separados.
  - Primeiro comando real recebe estado completo.
  - `/model` e `/effort` sao deduplicados por valor vigente.
  - `/clear` e omitido entre pares/cadeias contextuais conhecidas.

- [x] Corrigir heranca indevida em comandos interativos.
  - `_inject_clears` agora aplica a mesma regra de estado para comandos `AUTO` e `INTERACTIVE`.
  - Isso evita que `/delivery:sign-off` ou outro comando manual rode com model/effort herdado incorretamente.

- [x] Honrar metadata em `fold_in_rules`.
  - `CommandRef` aceita `model`, `effort`, `interaction`, `mandatory`, `source_ref`.
  - `emit_fold` usa metadata declarada e so cai para `opus/high/auto` quando ausente.

- [x] Persistir trail de carregamento da matrix.
  - Load via matrix grava evento `load-queue` no trail do modulo.
  - Falha de persistencia e nao bloqueante e fica em log.

- [x] Reforcar fixture smoke.
  - Snapshot smoke agora tem `command_index`, `phase_buckets`, `filter` e `loop_multiplier` reais.
  - Smoke valida que a fixture nao e uma matrix vazia que so testa fold-ins.

- [x] Adicionar testes de regressao puros.
  - `test_dcp_matrix_canonical.py` cobre enums, derivacao sem diretivas, render com diretivas, dedupe e fold-in metadata.

- [x] Atualizar regras/documentacao.
  - `ai-forge/rules/dcp-cmd-list-build.md` declara matrix como canonico runtime e `SPECIFIC-FLOW.json` como fallback legacy.
  - `ai-forge/rules/workflow-app-command-lists.md` declara o hardening de render: linhas separadas, clear por boundary, model/effort apenas quando mudam.

## Validacao executada

- [x] `PYTHONPATH=ai-forge/workflow-app/src pytest ai-forge/workflow-app/tests/test_dcp_matrix_canonical.py -q`
- [x] `PYTHONPATH=ai-forge/workflow-app/src pytest tests/dcp/test_fold_in_rules.py tests/dcp/test_smoke_dcp_matrix.py -q`
- [x] `PYTHONPATH=ai-forge/workflow-app/src pytest ai-forge/workflow-app/tests/test_dcp_matrix_canonical.py tests/dcp/test_fold_in_rules.py tests/dcp/test_smoke_dcp_matrix.py -q`
- [x] `QT_QPA_PLATFORM=offscreen PYTHONPATH=src pytest tests/test_dcp_specific_flow_handler.py tests/test_dcp_pipeline_auto_load.py tests/test_dcp_build_pipeline_handler.py tests/test_dcp_matrix_trail.py -q`
- [x] `PYTHONPATH=ai-forge/workflow-app/src python3 -m py_compile ...` nos modelos, derivadores, widget DCP e componentes UI tocados.

## Riscos residuais

- [x] Testes Qt do recorte DCP executados em `QT_QPA_PLATFORM=offscreen`: 68 passed, 9 warnings ja existentes de disconnect de signal.
- [ ] O fallback legacy `SPECIFIC-FLOW.json` continua existindo para compatibilidade. Remover esse fallback deve ser uma mudanca futura com migracao explicita.
