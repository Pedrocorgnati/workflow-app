# Telas do MiMo Code CLI (fixtures)

Capturas reais da tela RENDERIZADA do TUI do MiMo Code CLI (fork do opencode,
binario Bun), uma por estado. Sao a entrada de teste do classificador puro de
tela da lane MiMo do app (previsto pela area S2: `classify_mimo_screen` em
`output_panel/mimo_screen.py`) e ficam travadas por
`tests/test_mimo_screen_fixtures.py`.

## Origem

- Spike `mimo-cli-pty`, 2026-10-03, MiMo Code CLI v0.1.15.
- PTY real (`os.forkpty` com `zsh --login -i`) renderizado pelo pyte 0.8.2 do
  venv do app. A deteccao so vale na tela renderizada: no fluxo cru o mesmo
  texto chega fatiado por SGR/CUP.
- Geometria medida: 200 colunas x 50 linhas (`ready`, `busy`, `modal`,
  `dialog`, `bypass`) e 100 colunas x 40 linhas (`nomatch`, `fatal`).

## Formato

- Linha 1: `# t=<segundos desde o spawn> cursor=<linha>,<coluna> modes={...}`,
  com os modos DEC privados vistos pelo harness (`bp2004` bracketed paste,
  `m1000`/`m1002`/`m1003`/`sgr1006` mouse, `focus1004`, `cur25` cursor
  visivel, `sync2026`, `alt1049` tela alternativa).
- Depois, uma linha por linha da tela: `NN|<texto>`, sem espacos a direita.
- Unica alteracao em relacao a captura: o id da sessao no caminho do
  scratchpad virou zeros do mesmo tamanho, entao a geometria nao muda. O resto
  e verbatim, inclusive os glifos do TUI.

## Estados e agulhas

| Fixture | Estado | Agulha medida | Captura de origem |
|---|---|---|---|
| `ready.txt` | pronto (home) | `Type your message... (type / for commands)` e o rodape `/ commands` sem `esc interrupt` | run `r1`, boot +5.0 s |
| `busy.txt` | ocupado | `esc interrupt` no rodape | run `r1`, segundo prompt +0.3 s |
| `modal.txt` | modal de agente | `Select agent` (com `No results found`) | run `rS`, `argshell-quiet` |
| `dialog.txt` | pergunta do modelo | `↑↓ select  enter submit  esc dismiss` e `→ Asked 1 question` | run `rQ`, dialogo +0 s |
| `nomatch.txt` | comando inexistente | `No matching items` | run `rW2`, antes do Enter |
| `fatal.txt` | crash do TUI | `A fatal error occurred!` | run `rW`, home |
| `bypass.txt` | dialogo de bypass | `Bypass Permissions` | run `r0`, boot +0.5 s |

Precedencia: `modal.txt` e `nomatch.txt` TAMBEM mostram o rodape `/ commands`
sem `esc interrupt`, entao o classificador precisa testar as agulhas que
bloqueiam o envio antes do rodape de pronto. `dialog.txt` mostra
`Type your own answer`, que nao e a agulha de pronto.

`bypass.txt` so aparece quando o CLI sobe com a flag de linha de comando de
bypass (o default do dialogo e sair). O `mimod` liga o bypass pela variavel de
ambiente e nao passa por essa tela.

Lacunas conhecidas: nao ha captura abaixo de 100 colunas, da variante
`esc again` do rodape ocupado nem do estado `shell` (prompt do zsh sem TUI).

## Regras

- Regravar as fixtures ao trocar de versao do CLI, atualizando versao, data,
  geometria e agulhas deste README. O teste falha se uma agulha sumir.
- Nenhuma fixture carrega segredo (chave, valor de env, conteudo de config) nem
  o id da sessao de gravacao. Caminho de home e aceitavel.
- Este README nao reproduz as frases-gatilho de falha fatal escopada da MiMo.
  A fonte da verdade desses padroes e `output_panel._CLI_SCOPED_FATAL_PATTERNS`.
  A agulha `A fatal error occurred!` nao e um desses padroes e fica literal.
