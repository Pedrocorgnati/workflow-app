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
```

O sentinel de conclusão será adicionado automaticamente pelo autocast.
