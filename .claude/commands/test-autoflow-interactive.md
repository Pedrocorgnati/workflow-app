---
description: Comando de teste interativo para validar a parada do autocast. Aguarda 30s e finaliza.
---

# Test Autoflow Interactive

Este é um comando de teste INTERATIVO para validar que o autocast para ao encontrar um comando interativo.

Execute o seguinte script de teste:

```bash
echo "=== test-autoflow-interactive: iniciando (modo interativo) ==="
for i in $(seq 1 6); do
  echo "  tick $i/6..."
  sleep 5
done
echo "=== test-autoflow-interactive: concluído — pressione Enter para continuar o pipeline ==="
read -p "" _dummy
```

O autocast deve parar ANTES deste comando e aguardar intervenção manual.
