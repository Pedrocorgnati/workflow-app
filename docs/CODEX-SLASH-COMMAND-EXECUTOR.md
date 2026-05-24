# Codex Slash Command Executor

## Pergunta

Qual o melhor jeito de fazer o Codex ler e executar um comando do Claude,
por exemplo `/blog:init-strategy`, dentro do workflow-app?

## Decisao

Use um prompt executor que aponta para o markdown real em `.claude/commands/`
e para as regras em `ai-forge/MCP/agents/executor-de-slash-commands-rules.md`.

Formato produzido pelo workflow-app:

```text
Use the SystemForge slash-command executor rules and execute the Claude command below with maximum fidelity.

Executor rules: ai-forge/MCP/agents/executor-de-slash-commands-rules.md
Listener rules: ai-forge/rules/workflow-app-listeners.md
Expected listener channel: interactive
Command: /blog:init-strategy
Command markdown: /abs/path/.claude/commands/blog/init-strategy.md
Arguments: (none)
```

## Por que este caminho

A documentacao oficial do Codex descreve o Codex como agente capaz de ler
arquivos, editar codigo e executar comandos localmente. Ela tambem recomenda
fornecer contexto direto e arquivos relevantes ao prompt, e descreve skills
como workflows reutilizaveis carregados sob demanda.

Fontes:

- https://developers.openai.com/codex/cli
- https://developers.openai.com/codex/prompting
- https://developers.openai.com/codex/skills
- https://developers.openai.com/codex/subagents

A consulta via `skill-claude` chegou a mesma conclusao: a maior fidelidade
vem de ler o markdown original do comando. Duplicar todos os comandos Claude
como skills Codex cria drift operacional; pedir "simule o Claude" sem apontar
para a fonte real aumenta alucinacao.

## Alternativas consideradas

1. Prompt simples: "simule o Claude e execute /cmd".
   Resultado: rejeitado. O Codex nao tem a definicao atual do comando no
   prompt e tende a completar lacunas por inferencia.

2. Converter cada slash command em skill Codex.
   Resultado: rejeitado para uso geral. A manutencao duplicada de centenas de
   comandos em `.claude/commands/` e `.codex/skills/` criaria divergencia.

3. Prompt executor lendo `.claude/commands/{namespace}/{cmd}.md`.
   Resultado: aprovado. Mantem a fonte de verdade unica e funciona com os
   comandos existentes.

4. Agente dedicado.
   Resultado: aprovado como complemento. As regras ficam em
   `ai-forge/MCP/agents/executor-de-slash-commands-rules.md`; o workflow-app
   ainda monta o prompt com o caminho exato do comando.

## Regras implementadas no workflow-app

- `Main LLM = claude`: mantem o comportamento legado no terminal interativo.
- `Main LLM = kimi`: converte `/blog:x` em `/skill:blog:x` e envia ao T1.
- `Main LLM = codex`: envia ao T1 um prompt executor apontando para o
  markdown real em `.claude/commands/`, com `Expected listener channel:
  interactive`.
- `Parallel Worker = kimi`: preserva o comportamento antigo de `Use Kimi` no
  `Rodar proximo` para comandos compativeis.
- `Parallel Worker = codex`: no `Rodar proximo`, envia comandos Claude elegiveis
  ao Terminal 3 usando o mesmo prompt executor, com `Expected listener channel:
  workspace_xterm`.
- `/model` e `/effort` sao tratados como metadados de sessao e nao sao enviados
  nos modos principais Kimi/Codex.
- `/clear` e enviado ao terminal do LLM principal, ou aos workers marcados no
  modo Claude.

## Riscos

- Comandos que dependem de MCP exclusivo do Claude podem precisar de blocklist.
- Comandos orquestradores com subcomandos podem exigir leitura recursiva dos
  markdowns referenciados.
- Contexto conversacional do Claude nao existe automaticamente no Codex; o
  prompt precisa carregar caminhos e arquivos relevantes explicitamente.
- Se o prompt nao mencionar `workflow-app-listeners.md`, o Codex pode executar
  a tarefa e esquecer o bloco `## FASE FINAL`, deixando o listener amarelo. Por
  isso o prompt atual inclui `Listener rules`, `Expected listener channel` e a
  instrucao de preservar/executar `wf-notify` quando existir no comando.
