---
description: Comando de teste para validar o ciclo AUTO do autocast. Aguarda 30s e finaliza.
---

# Test Autoflow Auto

Este é um comando de teste para validar o ciclo de execução automática do autocast.

Execute o seguinte script de teste:

```bash
echo "=== test-autoflow-auto: iniciando ==="
for i in $(seq 1 6); do
  echo "  tick $i/6..."
  sleep 5
done
echo "=== test-autoflow-auto: concluído ==="
# WF_CHANNEL=workspace é setado pelo wrapper Kimi (.agents/skills/test-autoflow-auto.md).
# Sem wrapper (execução direta pelo Claude), usa "interactive" como canal correto.
: "${WF_CHANNEL:=interactive}"
python3 ai-forge/workflow-app/scripts/notify-terminal-idle.py "${WF_CHANNEL}" 2>/dev/null || true
```

O script `notify-terminal-idle.py` sinaliza ao workflow-app que o terminal ficou idle,
ativando o hardening de 2s antes de virar o dot verde.
O canal é determinado pela variável `WF_CHANNEL` (padrão: `interactive` para Claude,
`workspace` para Kimi — definido pelo wrapper `.agents/skills/test-autoflow-auto.md`).
