# Progress: fixture-tres-status-mais-invalido
Modo: --task
Source: (fixture congelada, sem source vivo)
Created: 2026-08-24T00:00:00Z
Total: 4 items | Done: 1 | Pending: 1 | Failed: 1

## Items

| ID  | Status | Target | Bucket | Updated |
|-----|--------|--------|--------|---------|
| 001 | [x]    | tasks/items/task-001-alfa.md | T-opus-high | 2026-08-24T01:00:00Z |
| 002 | [ ]    | tasks/items/task-002-beta.md | T-opus-high | -       |
| 003 | [!]    | tasks/items/task-003-gama.md | T-opus-high | 2026-08-24T02:00:00Z |
| 004 | [~]    | tasks/items/task-004-delta.md | T-opus-high | -       |

Nota da fixture: o cabecalho declara 4 items mas so soma 3 status canonicos.
A divergencia e proposital: o item 004 tem marcador invalido `[~]` e nao pode
ser contado como nenhum dos tres status. Ver CONTRACT.md secao 2.5.
