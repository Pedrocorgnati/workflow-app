---
description: "Fixture congelada: regra do Escopo exato contradiz a secao Notas"
model: opus
effort: high
scope: task
task_type: task
delegate_kind: implementation
mode_support:
- write
---

# Item 013 (reducao minima) - Impedir que intent nasca sem alvo

## Contexto

Reducao minima do fenomeno observado no item 013 do caso 08-19. Nao e copia do
arquivo vivo: preserva apenas o par de frases que se contradiz e o minimo de
contexto para a contradicao ser legivel.

## Objetivo

Rejeitar na origem o intent com campo obrigatorio ausente.

## Escopo exato

### BACKEND

**ST001 - [BACKEND] Validar campos obrigatorios antes de despachar o intent**
- **Arquivo:** `shared/entitlement-engine/rules-engine.ts`
- **Implementacao:**
  - Validar `targetId`, `groupEmail` e `externalPrincipal` como strings nao vazias
  - Quando faltar qualquer um, devolver array vazio
  - **Nao remover nem comentar o curto-circuito da linha 897:** ele continua
    sendo a saida legitima quando `targetId` vem explicito no payload. O que
    muda e que ele so emite intent com os tres campos completos
- **Resultado esperado:** intent incompleto e rejeitado na origem

## Criterios de aceite

- Nenhum intent com campo obrigatorio vazio e despachado
- O curto-circuito da linha 897 permanece no codigo

## Notas

- A guarda so dispara hoje para lista vazia de targets
- O curto-circuito atual em `buildJobsIntent` (linha 897) deve ser removido ou
  refinado para validar campos obrigatorios

<!--
CONTRADICAO CONGELADA (o ponto desta fixture):
  Escopo exato ST001 ordena "Nao remover nem comentar o curto-circuito da
  linha 897" e o repete em Criterios de aceite ("permanece no codigo");
  Notas ordena "deve ser removido ou refinado".
As duas instrucoes tem o mesmo alvo (linha 897) e sao mutuamente exclusivas na
leitura "removido". Um executor que le so a secao Notas apaga o ramo que o
criterio de aceite exige preservado.
-->
