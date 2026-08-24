# Fixtures minimas do corpus de loops

Congeladas em 2026-08-24 (Task 05 do estudo `08-24-systemforge-analise-fluxo-loop`).

Regra de ouro: **nenhum teste referencia diretorio vivo do corpus**. O caso de
origem (`blacksmith/loop-archives/08-19-conecta-clube-tasklist-ondas-0-4`) e
material vivo: continua sendo executado, editado e reordenado, entao usa-lo como
fixture faz o teste falhar por motivo alheio ao codigo. Estas fixtures sao
extracoes MINIMAS do fenomeno, nao copias do diretorio.

| Fixture | Fenomeno congelado |
|---|---|
| `config-sizing-comprimido.json` | sizing comprimido no bucket + override por item |
| `task-contradicao-minima.md` | regra do Escopo exato contradiz a secao Notas (derivado do item 013) |
| `progress-tres-status-mais-invalido.md` | tres status canonicos + um `invalid_marker` |
| `rocksmash-seed-sem-execucao.md` | seed rocksmash sem marcador de execucao |
| `rocksmash-execucao-parcial.json` | execucao rocksmash parcial por subfase |

Conteudo IMUTAVEL. Alterar uma fixture muda o significado do teste que a
consome; para cobrir um fenomeno novo, adicione outra fixture.
