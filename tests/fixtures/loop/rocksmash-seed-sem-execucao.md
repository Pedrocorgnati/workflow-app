# Seed rocksmash (fixture congelada, sem marcador de execucao)

Arvore decimal produzida por `/loop-rocksmash:prepare`. Este seed esta no estado
IMEDIATAMENTE ANTERIOR a qualquer execucao: nenhuma linha carrega marcador de
status, nenhuma subfase esta anotada como iniciada ou concluida.

O ponto da fixture: distinguir "seed nunca executado" de "seed executado sem
resultado". Sao estados diferentes e produzem decisoes diferentes no
`/loop-rocksmash:compare`; a ausencia de marcador NAO pode ser lida como
execucao vazia.

## 1. Corrigir a resolucao da assinatura

### 1.1 Ler a chave correta do payload
### 1.2 Cobrir o caminho com teste de contrato

## 2. Impedir que o grant nasca sem alvo

### 2.1 Validar campos obrigatorios antes do despacho
### 2.2 Remover o fallback nao-canonico no enqueue
### 2.3 Verificar o calculo do lock target

## 3. Fechar a onda

### 3.1 Rodar a suite completa
