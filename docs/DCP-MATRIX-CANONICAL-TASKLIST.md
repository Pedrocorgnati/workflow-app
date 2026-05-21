# TASKLIST - DCP Matrix Canonical Flow Hardening

## Resumo

Esta tasklist consolida as correcoes necessarias para tornar `DCP-COMMAND-MATRIX.json` a fonte canonica do fluxo DCP no `ai-forge/workflow-app`.

Decisoes confirmadas:

- `DCP-COMMAND-MATRIX.json` e o canonico.
- Enums devem ser alinhados entre regras, profile, schema, matrix e runtime do workflow-app.
- O botao com nome `DCP: Specific-Flow (load)` deve continuar existindo, mas deve renderizar a lista sequencial a partir da matrix canonica, nao depender de `SPECIFIC-FLOW.json` como fonte primaria.
- `SPECIFIC-FLOW.json` pode permanecer temporariamente como compatibilidade/fallback, mas nao deve ser tratado como fonte de verdade.

## Premissas

- Repositorio base: `/home/pedro/Repositórios/systemForge`.
- App alvo: `ai-forge/workflow-app`.
- Fonte atual de regras: `ai-forge/rules/dcp-cmd-list-build.md`.
- Profile historico do loop: `.claude/commands/_lib/specific_flow/profiles.py`.
- Runtime matrix do app: `ai-forge/workflow-app/src/workflow_app/models/dcp_command_matrix.py`.
- Derivacao da fila: `ai-forge/workflow-app/src/workflow_app/dcp/queue_derivation.py`.
- Handler dos botoes DCP: `ai-forge/workflow-app/src/workflow_app/command_queue/command_queue_widget.py`.

## Objetivo Final

Ao final da execucao:

- O contrato documentado deve declarar explicitamente `DCP-COMMAND-MATRIX.json` como fonte canonica.
- A matrix deve conseguir representar todos os comandos/fases/modelos/interacoes necessarios do loop A..I.
- O botao `DCP: Specific-Flow (load)` deve carregar a fila sequencial diretamente da matrix.
- O fallback via `SPECIFIC-FLOW.json` deve ser seguro, explicitamente legado e coberto por testes.
- A suite deve ter testes de paridade suficientes para impedir regressao silenciosa entre `profiles.py`, matrix e UI.

## Lista Sequencial de Tarefas

### 1. Atualizar contrato canonico DCP para matrix-first

Arquivos principais:

- `ai-forge/rules/dcp-cmd-list-build.md`
- `WORKFLOW-DETAILED.md`
- `CLAUDE.md`
- `WORKFLOW.md`

Procedimento:

1. Alterar o titulo e a introducao de `dcp-cmd-list-build.md` para declarar `DCP-COMMAND-MATRIX.json` como fonte canonica runtime.
2. Rebaixar `SPECIFIC-FLOW.json` para artefato legado/fallback/compatibilidade.
3. Atualizar a secao de referencias para apontar tambem para:
   - `ai-forge/workflow-app/src/workflow_app/models/dcp_command_matrix.py`
   - `ai-forge/workflow-app/src/workflow_app/dcp/queue_derivation.py`
   - `.claude/commands/_lib/build_module_pipeline.py`
4. Manter `profiles.py` como fonte historica de inventario do loop, mas nao como runtime authority isolada.
5. Documentar o fluxo correto:
   - matrix init/refine/replicate/filter/mark-loops
   - `/build-module-pipeline` valida e marca `current_module`
   - workflow-app carrega fila via `derive_queue_from_matrix`
6. Remover ou corrigir frases que dizem que o `SPECIFIC-FLOW.json` gerado completo e a fonte autoritativa.

Critérios de aceite:

- Nenhum documento principal afirma que `SPECIFIC-FLOW.json` e a fonte primaria do runtime DCP.
- `dcp-cmd-list-build.md` explica claramente a relacao entre matrix, profile e fallback.
- A secao de troubleshooting diferencia erro de matrix ausente de fallback legado.

### 2. Alinhar enums de fase entre profile, matrix e derivador

Arquivos principais:

- `ai-forge/workflow-app/src/workflow_app/models/dcp_command_matrix.py`
- `ai-forge/workflow-app/src/workflow_app/dcp/queue_derivation.py`
- `.claude/commands/_lib/specific_flow/profiles.py`
- `.claude/commands/_lib/specific_flow/schema.json`

Problema atual:

- `queue_derivation.PHASE_ORDER` usa fases como `B-tdd` e `B-dcp`.
- `DcpCommandMatrix.PhaseLiteral` nao aceita `B-tdd` nem `B-dcp`.
- O contrato de regras ainda fala em fases `FASE_B_TDD`, `FASE_B2_BUILD`, `FASE_D_F8`, etc.

Procedimento:

1. Definir uma tabela canonica de fases internas da matrix.
2. Escolher nomes internos estaveis, preferencialmente:
   - `A-creation`
   - `B-tdd`
   - `B-build`
   - `B-dcp`
   - `B3-execute`
   - `C-linkage`
   - `D-f8-micro`
   - `D5-review`
   - `E-qa-micro`
   - `F-stack-plan`
   - `F2-stack-check`
   - `G-deploy`
   - `H-commit`
   - `I-human-signoff`
   - `I-human-mkt`
3. Atualizar `PhaseLiteral` para aceitar todos os valores usados por `PHASE_ORDER`.
4. Atualizar validadores em `DcpCommandMatrix._check_invariants`.
5. Criar mapa de exibicao separado para UI, se necessario:
   - interno: `B-tdd`
   - display: `FASE_B_TDD`
6. Garantir que `phase_buckets` rejeite fases desconhecidas, mas aceite todas as fases canonicas.

Critérios de aceite:

- Uma matrix com comandos `B-tdd` valida via Pydantic.
- Uma matrix com bucket `B-dcp` valida via Pydantic.
- `derive_queue_from_matrix` nao referencia fase que o schema rejeita.
- Teste unitario cobre cada fase canonica pelo menos uma vez.

### 3. Alinhar enums de model, effort e interaction

Arquivos principais:

- `ai-forge/workflow-app/src/workflow_app/models/dcp_command_matrix.py`
- `ai-forge/workflow-app/src/workflow_app/dcp/queue_derivation.py`
- `ai-forge/workflow-app/src/workflow_app/domain.py`
- `.claude/commands/_lib/specific_flow/schema.json`
- `ai-forge/rules/dcp-cmd-list-build.md`

Problema atual:

- Regra documenta `sonnet`, mas `DcpCommandMatrix.ModelLiteral` aceitava apenas `opus|sonnet`.
- `SPECIFIC-FLOW` aceita `manual`, mas matrix aceita `interactive|headless`.
- `EffortLevel` do app aceita `max`, mas matrix aceita apenas `low|medium|high`.

Procedimento:

1. Decidir semantica canonica:
   - `sonnet` deve ser valor aceito pelo contrato se continuar documentado.
   - Recomendacao: aceitar `sonnet` na matrix e mapear para `ModelName.SONNET` no workflow-app.
2. Atualizar `ModelLiteral` para aceitar `sonnet`, se a documentacao continuar citando `sonnet`.
3. Atualizar `EffortLiteral` para aceitar `max`, se o app continuar expondo `EffortLevel.MAX`.
4. Atualizar `InteractionLiteral` para aceitar os dois vocabularios ou criar normalizacao explicita:
   - `auto` -> `headless`
   - `manual` -> `interactive`
   - `headless` -> `auto`
   - `interactive` -> `inter`
5. Preferir normalizacao em uma funcao unica, por exemplo:
   - `normalize_matrix_model`
   - `normalize_matrix_effort`
   - `normalize_matrix_interaction`
6. Garantir mensagens de erro claras quando valor desconhecido aparecer.

Critérios de aceite:

- Matrix com `model: "sonnet"` valida ou falha com mensagem documentada. Nao pode falhar de forma contraditoria com a regra.
- Matrix com `interaction: "manual"` valida ou e migrada automaticamente para equivalente canonico.
- Matrix com `effort: "max"` valida se o UI permite esse valor.
- Testes cobrem aliases e valores invalidos.

### 4. Criar camada unica de normalizacao de contratos

Arquivos principais:

- `ai-forge/workflow-app/src/workflow_app/dcp/queue_derivation.py`
- `ai-forge/workflow-app/src/workflow_app/models/dcp_command_matrix.py`
- Novo arquivo sugerido: `ai-forge/workflow-app/src/workflow_app/dcp/contract_normalizer.py`

Procedimento:

1. Extrair mapas de phase/model/effort/interaction para um modulo unico.
2. Evitar duplicacao entre:
   - Pydantic model
   - derivador de fila
   - handlers do widget
   - testes
3. Expor funcoes puras:
   - `canonical_phase(value: str) -> str`
   - `to_command_model(value: str) -> ModelName`
   - `to_command_effort(value: str) -> EffortLevel`
   - `to_command_interaction(value: str) -> InteractionType`
4. Usar essas funcoes em `derive_queue_from_matrix`.
5. Documentar aliases legados no proprio modulo.

Critérios de aceite:

- Nao ha mapas paralelos divergentes para model/effort/interaction.
- Teste de roundtrip cobre todos os valores aceitos.
- Adicionar um novo model/effort exige alterar um unico local principal.

### 5. Fazer o botao `DCP: Specific-Flow (load)` carregar pela matrix

Arquivos principais:

- `ai-forge/workflow-app/src/workflow_app/command_queue/command_queue_widget.py`
- `ai-forge/workflow-app/src/workflow_app/dcp/specific_flow_handler.py`
- `ai-forge/workflow-app/src/workflow_app/dcp/queue_derivation.py`

Procedimento:

1. Renomear mentalmente o comportamento sem quebrar a label:
   - Label continua `DCP: Specific-Flow (load)`.
   - Comportamento primario vira `Matrix Load`.
2. Em `_on_dcp_specific_flow_clicked`, resolver projeto e `delivery.json`.
3. Determinar `cm_id` atual:
   - se `current_module` existe e nao esta `done`, usar ele.
   - se `current_module` esta `done`, usar proximo nao-done.
   - se `parallel-independent`, exigir selecao explicita em card de modulo ou abortar com mensagem clara.
4. Tentar carregar `DCP-COMMAND-MATRIX.json` antes de procurar `SPECIFIC-FLOW.json`.
5. Validar:
   - matrix existe.
   - schema valido.
   - `cm_id` existe em `matrix.modules`.
   - `filter` tem mesmo tamanho de `command_index`.
   - `loop_multiplier` tem valores coerentes para fases per-task.
6. Derivar fila com `derive_queue_from_matrix`.
7. Emitir `signal_bus.pipeline_ready.emit(queue)`.
8. Atualizar label da fila para indicar origem:
   - `DCP Matrix: {cm_id}`
9. Usar `SPECIFIC-FLOW.json` apenas se:
   - matrix ausente, e
   - usuario estiver em modo legado/fallback, ou
   - houver configuracao explicita permitindo fallback.

Critérios de aceite:

- Clicar `DCP: Specific-Flow (load)` com matrix valida renderiza lista sequencial sem exigir `SPECIFIC-FLOW.json`.
- Se matrix estiver ausente, mensagem orienta rodar o fluxo de matrix, nao apenas procurar `SPECIFIC-FLOW.json`.
- Fallback legado e visivelmente identificado no toast/log.
- Teste cobre load via matrix sem arquivo `SPECIFIC-FLOW.json` no disco.

### 6. Remover dependencia obrigatoria do stub `SPECIFIC-FLOW.json`

Arquivos principais:

- `.claude/commands/_lib/build_module_pipeline.py`
- `ai-forge/workflow-app/src/workflow_app/command_queue/command_queue_widget.py`
- `ai-forge/workflow-app/src/workflow_app/services/delivery_reader.py`

Problema atual:

- `/build-module-pipeline` gera um stub vazio de `SPECIFIC-FLOW.json`.
- O local-action verifica esse arquivo antes de tentar derivar da matrix.
- Se o stub nao for escrito, o fluxo pode falhar mesmo com matrix valida.

Procedimento:

1. Alterar `_handle_dcp_load_specific_flow` para tentar matrix primeiro.
2. Somente depois tentar resolver `SPECIFIC-FLOW.json`.
3. Rebaixar `_generate_specific_flow_json` para compatibilidade opcional.
4. Se manter stub, torna-lo explicitamente best-effort e nao necessario para sucesso do workflow-app.
5. Atualizar mensagens:
   - erro primario deve falar de matrix.
   - `SPECIFIC-FLOW.json nao apareceu` deve ser apenas fallback legado.

Critérios de aceite:

- Fluxo B-dcp completo funciona quando `SPECIFIC-FLOW.json` nao existe.
- Stub vazio nao e carregado como fila principal.
- Teste remove o stub e confirma que a fila vem da matrix.

### 7. Materializar diretivas `/clear`, `/model`, `/effort` na fila derivada da matrix

Arquivos principais:

- `ai-forge/workflow-app/src/workflow_app/dcp/queue_derivation.py`
- `ai-forge/workflow-app/src/workflow_app/command_queue/command_queue_widget.py`
- `ai-forge/workflow-app/src/workflow_app/daily_loop/loader.py` como referencia de dedupe
- `.claude/commands/_lib/specific_flow/generator.py` como referencia historica

Problema atual:

- `derive_queue_from_matrix` emite comandos reais sem diretivas.
- No caminho manual, o terminal recebe apenas `spec.name`.
- No runner automatico, `effort` nao e passado como flag CLI e depende de diretiva ou suporte futuro.

Procedimento:

1. Definir politica:
   - A fila visual deve conter directives, igual quick templates.
   - Ou o runner deve aplicar model/effort por comando sem directives.
2. Recomendacao: materializar directives para manter compatibilidade com caminho manual e terminal interativo.
3. Implementar `insert_matrix_directives(queue_or_entries)` usando:
   - `model`
   - `effort`
   - grupos/contexto compartilhado se disponivel.
4. Se `matrix.modules[cm_id].directive_boundaries` existir, honrar boundaries gravadas.
5. Se nao existir, recalcular boundaries com dedupe seguro:
   - primeiro comando: `/clear`, `/model`, `/effort`.
   - troca de contexto: `/clear`.
   - troca de model: `/model`.
   - troca de effort: `/effort`.
   - comandos de cadeia contextual podem suprimir `/clear` se grupo for conhecido.
6. Garantir que directives nao recebam `config_path`.

Critérios de aceite:

- Fila carregada pela matrix contem directives suficientes para execucao manual correta.
- `/effort` aparece antes de comandos high/low quando necessario.
- Teste compara uma fila matrix com a politica de directives documentada.

### 8. Corrigir `fold_in_rules` para preservar metadata de comando

Arquivos principais:

- `ai-forge/workflow-app/src/workflow_app/models/dcp_command_matrix.py`
- `ai-forge/workflow-app/src/workflow_app/dcp/queue_derivation.py`
- `.claude/commands/_lib/specific_flow/profiles.py`

Problema atual:

- `fold_in_rules` usa `CommandRef`, que nao carrega `model`, `effort`, `interaction`, `mandatory` ou `source_ref`.
- O derivador força tudo para `Opus/high`.

Procedimento:

1. Estender `CommandRef` para aceitar metadata opcional:
   - `model`
   - `effort`
   - `interaction`
   - `mandatory`
   - `source_ref`
   - `condition`
2. Definir defaults compatíveis quando campos faltarem.
3. Alterar `emit_fold` para usar metadata real do `CommandRef`.
4. Popular fold-ins gerados com metadata correta:
   - H commit: conforme profile.
   - I signoff: conforme profile.
   - G deploy: conforme comando.
   - I mkt: conforme comando.
5. Se possivel, evitar duplicacao apontando fold-in para indice do `command_index`.

Critérios de aceite:

- `/commit:*` derivado da matrix nao aparece forçado como `Opus/high` se o profile define outro valor.
- `/delivery:sign-off` continua `Opus/high`.
- Teste cobre fold-in com metadata customizada.

### 9. Adicionar preflight de matrix no botao `DCP: Build + Load`

Arquivos principais:

- `ai-forge/workflow-app/src/workflow_app/command_queue/command_queue_widget.py`
- `ai-forge/workflow-app/src/workflow_app/dcp/queue_derivation.py`

Procedimento:

1. Em `_dcp_build_preflight`, apos validar `MODULE-META.json`, resolver `dcp_root`.
2. Verificar existencia de `DCP-COMMAND-MATRIX.json`.
3. Validar schema Pydantic.
4. Verificar `matrix.modules[cm_id]`.
5. Verificar cardinalidade e multipliers.
6. Se falhar, exibir mensagem com comando de reparo sugerido:
   - `/dcp:matrix-init`
   - `/dcp:matrix-replicate`
   - `/dcp:matrix-filter-modules`
   - `/dcp:matrix-mark-loops`
7. Nao enfileirar B-dcp se matrix esta estruturalmente impossivel de usar.

Critérios de aceite:

- Botao falha antes de iniciar subprocessos quando matrix esta ausente ou corrupta.
- Mensagem e acionavel.
- Teste cobre matrix ausente, modulo ausente e filter length errado.

### 10. Persistir evidencia de load da matrix

Arquivos principais:

- `ai-forge/workflow-app/src/workflow_app/dcp/queue_derivation.py`
- `ai-forge/workflow-app/src/workflow_app/command_queue/command_queue_widget.py`
- `ai-forge/workflow-app/src/workflow_app/models/dcp_matrix_trail.py`

Problema atual:

- `build_load_queue_trail_entry` cria entrada, mas o append e apenas em memoria.

Procedimento:

1. Criar writer atomico de trail para o evento `load-queue`.
2. Usar lock leve da matrix ou seguir protocolo existente de locks `.dcp-matrix-*.lock`.
3. Persistir:
   - `cm_id`
   - `queue_size`
   - `is_last`
   - `source=workflow-app`
   - timestamp UTC
4. Truncar/arquivar trail se exceder `trail_max_entries`.
5. Se persistencia falhar, emitir warning sem bloquear o load.

Critérios de aceite:

- Apos carregar fila pela matrix, `matrix.modules[cm_id].trail` registra `action=load-queue`.
- Falha de escrita nao impede operador, mas gera toast/log.
- Teste cobre persistencia e fallback em erro de IO.

### 11. Migrar overrides de skip para matrix

Arquivos principais:

- `ai-forge/workflow-app/src/workflow_app/command_queue/command_queue_widget.py`
- `ai-forge/workflow-app/src/workflow_app/dcp/queue_derivation.py`
- `ai-forge/workflow-app/src/workflow_app/models/dcp_command_matrix.py`

Problema atual:

- `_persist_dcp_skip` grava `overrides.skipped[]` no `SPECIFIC-FLOW.json`.
- Matrix ja tem `modules[cm_id].overrides_skipped`, mas o fluxo visual nao persiste nele.

Procedimento:

1. Quando fila foi carregada da matrix, armazenar contexto:
   - `current_dcp_matrix_path`
   - `current_dcp_module_id`
2. Ao remover item da fila, gravar em `matrix.modules[cm_id].overrides_skipped`.
3. Preservar comportamento legado para fila carregada de `SPECIFIC-FLOW.json`.
4. Usar escrita atomica e validar Pydantic antes de salvar.
5. Registrar trail de override manual.

Critérios de aceite:

- Remover comando de fila matrix persiste skip na matrix.
- Recarregar `DCP: Specific-Flow (load)` nao traz o comando removido.
- Remover comando de fila legado continua persistindo no JSON legado.

### 12. Criar teste de paridade FULL_PROFILE -> matrix -> queue

Arquivos sugeridos:

- `tests/dcp/test_matrix_profile_parity.py`
- `ai-forge/workflow-app/tests/test_dcp_matrix_queue_parity.py`

Procedimento:

1. Criar fixture de MODULE-META representativa com:
   - frontend true
   - backend true
   - TDD required
   - deploy preview
   - docs/dependencies/env additions
   - user-facing surface true
2. Gerar lista esperada a partir de `FULL_PROFILE` ou snapshot controlado.
3. Criar `DCP-COMMAND-MATRIX.json` equivalente.
4. Derivar fila via `derive_queue_from_matrix`.
5. Comparar:
   - comandos obrigatorios presentes.
   - fases em ordem.
   - model/effort/interactions preservados.
   - directives presentes quando a fila for renderizada para UI.
6. Criar fixture negativa com enum invalido e garantir erro claro.

Critérios de aceite:

- Teste falha se `PhaseLiteral` rejeitar fase usada pelo derivador.
- Teste falha se `sonnet`/`manual` documentados nao forem suportados ou migrados.
- Teste falha se comandos criticos como `/build-verify`, `/review-executed-module`, `/validation-summary`, `/commit:*`, `/delivery:sign-off` sumirem.

### 13. Fortalecer smoke tests de matrix

Arquivos principais:

- `tests/dcp/test_smoke_dcp_matrix.py`
- `tests/dcp/fixtures/smoke-slug/expected/DCP-COMMAND-MATRIX.json`

Problema atual:

- O fixture smoke tem `command_index: []`, entao testa apenas fold-ins.

Procedimento:

1. Adicionar pelo menos 8 comandos reais ao `command_index`:
   - A creation per-task
   - B tdd
   - B build
   - B3 execute per-task
   - E qa
   - F stack
   - H commit
   - I signoff
2. Adicionar `phase_buckets` reais.
3. Adicionar `loop_multiplier` com `A-creation` e `B3-execute`.
4. Validar queue final com mais que tail.

Critérios de aceite:

- Smoke falha se `command_index` estiver vazio.
- Smoke valida pelo menos um comando per-task expandido.
- Smoke valida directives se forem materializadas no derivador.

### 14. Atualizar mensagens e labels do workflow-app

Arquivos principais:

- `ai-forge/workflow-app/src/workflow_app/command_queue/command_queue_widget.py`
- `ai-forge/workflow-app/src/workflow_app/main_window.py`

Procedimento:

1. Manter botao `DCP: Specific-Flow (load)`, mas atualizar tooltip:
   - "Carrega a fila sequencial DCP a partir da matrix canonica. `SPECIFIC-FLOW.json` e fallback legado."
2. Atualizar mensagens de erro:
   - matrix ausente
   - matrix invalida
   - modulo ausente na matrix
   - fallback legado acionado
3. Atualizar label de template da fila:
   - `DCP Matrix: {cm_id}`
   - `DCP Legacy Specific-Flow: {cm_id}` quando fallback.

Critérios de aceite:

- Operador entende se esta no caminho canonico ou legado.
- Nenhuma mensagem primaria manda apenas "execute Specific-Flow primeiro" quando o problema real e matrix.

### 15. Revisar `/build-module-pipeline` apos matrix-first

Arquivos principais:

- `.claude/commands/_lib/build_module_pipeline.py`
- `.claude/commands/build-module-pipeline.md`

Procedimento:

1. Atualizar docstring e markdown para refletir contrato final.
2. Manter validacoes:
   - delivery exists
   - MODULE-META valid
   - dependencies done
   - skeleton gate
   - I-02
   - matrix validates
3. Remover linguagem de "gera SPECIFIC-FLOW completo".
4. Se stub continuar existindo:
   - marcar como compatibilidade temporaria.
   - nao fazer sucesso depender dele.
5. Adicionar output em `--json` indicando:
   - `matrix_path`
   - `current_module`
   - `specific_flow_stub_written: true|false`

Critérios de aceite:

- Markdown do comando bate com implementacao.
- Exit codes documentados batem com codigo.
- Nao ha promessa de `last_specific_flow` persistente em delivery v2.

### 16. Validar com testes automatizados

Comandos sugeridos:

```bash
cd ai-forge/workflow-app
pytest tests/test_dcp_specific_flow_handler.py tests/test_dcp_pipeline_auto_load.py tests/test_dcp_build_pipeline_handler.py tests/test_dcp_matrix_trail.py -q
```

```bash
cd /home/pedro/Repositórios/systemForge
PYTHONPATH=ai-forge/workflow-app/src pytest tests/dcp/test_fold_in_rules.py tests/dcp/test_smoke_dcp_matrix.py -q
```

```bash
cd /home/pedro/Repositórios/systemForge
PYTHONPATH=ai-forge/workflow-app/src pytest tests/dcp/test_matrix_profile_parity.py -q
```

Observacao:

- Em ambiente headless, testes Qt podem abortar no fixture `qapp`. Se isso ocorrer, rodar com configuracao Qt offscreen ou separar testes puros de testes UI.

Critérios de aceite:

- Testes puros de matrix passam.
- Testes de widget passam em ambiente Qt configurado.
- Nenhum teste depende de `SPECIFIC-FLOW.json` para o caminho canonico.

### 17. Criar checklist de regressao manual no workflow-app

Procedimento:

1. Abrir workflow-app.
2. Carregar projeto DCP com `dcp_root` configurado.
3. Clicar `DCP: Build + Load (pipeline)`.
4. Rodar os 6 itens da pipeline B-dcp.
5. Confirmar que o item local carrega a fila sequencial pela matrix.
6. Limpar/remover temporariamente `SPECIFIC-FLOW.json` e repetir o load.
7. Confirmar que `DCP: Specific-Flow (load)` ainda carrega pela matrix.
8. Remover um comando visualmente.
9. Recarregar e confirmar que skip persistiu em `matrix.modules[cm_id].overrides_skipped`.
10. Validar que `/clear`, `/model` e `/effort` aparecem onde necessario.

Critérios de aceite:

- Fluxo funciona sem stub.
- Operador consegue ver origem matrix.
- Skip persiste.
- Directives executam no modo manual.

## Checkpoints de Validacao

### Checkpoint A - Contrato

- `dcp-cmd-list-build.md` atualizado para matrix-first.
- Documentos principais sem contradicao sobre fonte canonica.

### Checkpoint B - Schema

- `DcpCommandMatrix` aceita todas as fases usadas pelo derivador.
- Model/effort/interaction alinhados.

### Checkpoint C - UI Load

- `DCP: Specific-Flow (load)` carrega pela matrix.
- Fallback legado e opcional e identificado.

### Checkpoint D - Runtime

- Fila renderizada contem commands reais e directives necessarias.
- Build + Load nao depende de stub.

### Checkpoint E - Auditoria

- Trail `load-queue` persistido.
- Overrides persistidos na matrix.

### Checkpoint F - Testes

- Testes puros passam.
- Testes Qt passam em ambiente configurado.
- Smoke com `command_index` real passa.

## Ordem Recomendada de Execucao

1. Atualizar contrato e docs.
2. Alinhar enums de fase/model/effort/interaction.
3. Criar normalizador unico.
4. Ajustar derivacao da matrix.
5. Ajustar botao `DCP: Specific-Flow (load)` para matrix-first.
6. Remover dependencia obrigatoria do stub.
7. Implementar directives na fila matrix.
8. Corrigir fold-ins.
9. Adicionar preflight matrix no Build + Load.
10. Persistir trail e overrides.
11. Expandir testes.
12. Rodar regressao manual.

## Riscos e Mitigacoes

| Risco | Impacto | Mitigacao |
|---|---:|---|
| Drift entre `profiles.py` e matrix | Alto | Teste de paridade FULL_PROFILE -> matrix -> queue |
| Quebra de projetos legados com `SPECIFIC-FLOW.json` | Medio | Manter fallback legado por feature flag ou fallback explicito |
| Directives duplicadas ou ausentes | Alto | Testes de boundary e execucao manual |
| Matrix corrupta bloquear workflow | Medio | Preflight acionavel com comandos de reparo |
| Qt headless dificultar CI | Medio | Separar testes puros de testes UI e configurar `QT_QPA_PLATFORM=offscreen` |
| Overrides perdidos na migracao | Medio | Migrar skips legados para `overrides_skipped` quando possivel |

## Definicao de Pronto

- `DCP-COMMAND-MATRIX.json` e documentado e implementado como fonte canonica.
- `DCP: Specific-Flow (load)` renderiza a fila sequencial pela matrix.
- `SPECIFIC-FLOW.json` nao e requisito para o caminho canonico.
- Enums estao alinhados.
- Directives sao preservadas ou substituidas por mecanismo equivalente comprovado.
- Testes de paridade e smoke real impedem regressao.
