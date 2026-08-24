---
description: "Fixture congelada: task densa, longa e VALIDA. Precisa PASSAR na rubrica de coerencia"
model: opus
effort: high
scope: task
task_type: task
delegate_kind: implementation
mode_support:
- write
---

# Item 014 (fixture positiva) - Rejeitar assinatura sem provider resolvido

## Contexto

Esta fixture existe para provar o lado dificil do gate: uma task **valida** que
e longa, cita muito codigo, tem Notas ricas, declara impacto fora da lista de
arquivos de origem e usa ramificacao condicional. Nada aqui pode virar achado.

`loadBillingEvent` em `shared/entitlement-engine/prisma-rules-engine.repository.ts`
(linha 128) so enriquece o payload quando a `ProviderSubscription` resolve.

**Arquivos:**
- `shared/entitlement-engine/prisma-rules-engine.repository.ts`
- `shared/entitlement-engine/enqueue-command.ts`

## Objetivo

Fazer `loadBillingEvent` devolver decisao explicita quando o provider nao
resolve, em vez de propagar payload silenciosamente incompleto.

## Pre-requisitos

- [PRE001] `shared/entitlement-engine/prisma-rules-engine.repository.ts` existe e e legivel
- [PRE002] `extractProviderCheckoutId` (linha 112) le `payload.payment.subscription`

## Escopo exato

### BACKEND

**ST001 - [BACKEND] Devolver decisao explicita quando o provider nao resolve**
- **Arquivo:** `shared/entitlement-engine/prisma-rules-engine.repository.ts`
- **Implementacao:**
  - Em `loadBillingEvent` (linha 128), quando `ProviderSubscription` nao resolver,
    devolver `EngineDecision` com `reason: UNRESOLVED_PROVIDER`
  - Manter `extractProviderCheckoutId` (linha 112) intacto: ele ja le a chave certa
  - Sobre o ramo de fallback de `resolveByEmail` (linha 156): **quando** o payload
    trouxer `externalPrincipal`, preservar o ramo; **caso contrario**, remover o
    ramo, porque sem `externalPrincipal` ele nunca casa e so gasta uma query
- **Resultado esperado:** payload incompleto vira decisao nomeada, nao job orfao

**ST002 - [BACKEND] Cobrir a decisao nova com teste**
- **Arquivo:** `shared/entitlement-engine/__tests__/repository.test.ts`
- **Implementacao:**
  - Cenario: evento sem `ProviderSubscription` correspondente
  - Resultado esperado: `reason: UNRESOLVED_PROVIDER` e `jobsIntent: []`
- **Dependencias:** ST001

## Saida esperada

- `loadBillingEvent` devolve `UNRESOLVED_PROVIDER` em vez de payload incompleto
- Teste novo em `shared/entitlement-engine/__tests__/repository.test.ts` cobrindo o caso

## Criterios de aceite

- [ST001] `loadBillingEvent` nunca propaga payload sem `planId` resolvido
- [ST002] O teste reprova antes da correcao e passa depois
- `extractProviderCheckoutId` (linha 112) permanece sem alteracao

## Verificacao

```bash
pnpm --filter @conecta-clube/shared test
```

## Notas

- A guarda `MISSING_DRIVE_TARGETS` (`applyGrantDecision`, linha 279) ja existe e
  cobre outro caso: lista vazia de targets. Nao e a mesma decisao
- **Impacto declarado fora da lista de arquivos de origem:** o filtro de busca
  `{ lockTarget: { contains: query.q } }` em `shared/admin/jobs.service.ts`
  (linha 448) passa a ver menos jobs, porque jobs condenados deixam de nascer.
  A perda e de conveniencia de busca, nao de capacidade
- `hipotese:` o volume de `UNRESOLVED_PROVIDER` deve ser residual apos o item 010,
  mas isso nao foi medido

<!--
POR QUE ESTA FIXTURE PRECISA PASSAR:
  - tem Notas ricas, mas descritivas: nenhuma ordem que negue o corpo normativo;
  - tem uma proibicao ("manter extractProviderCheckoutId intacto") coerente com o
    aceite, que repete a mesma preservacao;
  - tem remover E preservar sobre o MESMO alvo (o ramo da linha 156), porem com
    qualificador explicito que separa os casos ("quando" / "caso contrario"):
    isso e ramificacao, nao contradicao (rubrica secao 4, condicao 3);
  - toda citacao de linha vem colada a um simbolo entre crases (rubrica secao 5).
Se o gate reprovar esta fixture, o gate esta errado, nao a task.
-->
