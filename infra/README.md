# Infraestrutura — Workflow App

**Ferramenta IaC:** Docker Compose (CI/headless) + Scripts de deploy desktop
**Hosting:** Desktop (Linux)
**Ambientes:** Dev/local

---

## Estrutura

```
infra/
├── README.md
└── scripts/
    ├── install.sh          # Instala dependências desktop
    ├── run.sh              # Inicia o app
    ├── health-check.sh     # Verifica WebSocket server (workflow-mobile)
    └── tailscale-check.sh  # Verifica rede Tailscale (workflow-mobile)

docker-compose.yml          # CI local: test, lint, typecheck, ci, ws-test, ci-full
Dockerfile                  # Multi-stage: base → deps → dev
Makefile                    # Atalhos para comandos comuns
```

---

## Desenvolvimento Local

### Pré-requisitos

- Python 3.10+
- uv (`curl -Ls https://astral.sh/uv/install.sh | sh`)
- PySide6 >= 6.6.0 (inclui QtWebSockets para workflow-mobile)
- Tailscale (para feature workflow-mobile)

### Instalação

```bash
./infra/scripts/install.sh
```

### Rodar o app

```bash
./infra/scripts/run.sh

# Com opções:
./infra/scripts/run.sh --db-path ~/.workflow-app/prod.db --log-level DEBUG
```

Variáveis de ambiente aceitas:
| Variável | Default | Descrição |
|----------|---------|-----------|
| `DB_PATH` | `~/.workflow-app/workflow_app.db` | Caminho do banco SQLite |
| `LOG_LEVEL` | `INFO` | Nível de log (DEBUG, INFO, WARNING, ERROR) |

---

## Docker Compose (CI local)

### Perfis disponíveis

| Perfil | Comando | Descrição |
|--------|---------|-----------|
| `test` | `make docker-test` | Suite completa (pytest headless) |
| `lint` | `make docker-lint` | Ruff check |
| `typecheck` | `make docker-typecheck` | Mypy |
| `ci` | `make docker-ci` | lint + typecheck + test |
| `ws-test` | `make docker-ws-test` | Testes de integração WebSocket (workflow-mobile) |
| `ci-full` | `make docker-ci-full` | CI completo incluindo ws-test |

### Variáveis de ambiente (Docker)

| Variável | Valor no container | Descrição |
|----------|-------------------|-----------|
| `QT_QPA_PLATFORM` | `offscreen` | Qt headless (sem display X11) |
| `WS_BIND_HOST` | `127.0.0.1` | Host de bind para testes WebSocket |
| `WS_PORT` | `8765` | Porta do WebSocket server |
| `DB_PATH` | `""` | Banco em memória para testes |

---

## WebSocket Server — workflow-mobile

O `RemoteServer` (QWebSocketServer) faz bind na **interface Tailscale** (100.x.x.x):
- Porta primária: **8765**; fallback automático: 8766–8774
- Protocolo: JSON bidirecional com envelope `message_id` UUID

### Verificar Tailscale

```bash
./infra/scripts/tailscale-check.sh
```

Saída esperada:
```
  Tailscale ativo — OK
  IP Tailscale: 100.x.x.x — OK
  Interface tailscale0 — OK

  WS_BIND_HOST=100.x.x.x
  WS_PORT=8765
  No app Android: conectar em ws://100.x.x.x:8765
```

### Verificar WebSocket server (com app rodando)

```bash
# Localhost (dev)
./infra/scripts/health-check.sh 127.0.0.1 8765

# Via Tailscale
./infra/scripts/health-check.sh 100.x.x.x 8765
```

### Testes WebSocket em Docker

```bash
make docker-ws-test
# ou
docker compose --profile ws-test run --rm ws-test
```

---

## Variáveis de Ambiente

Não há `.env` de produção (app desktop sem servidor). Configurações runtime são passadas via:
- Variáveis de shell (`DB_PATH`, `LOG_LEVEL`)
- UI do app (toggle modo remoto, IP/porta WebSocket via SharedPreferences no Android)

---

## Dependências do Sistema (Ubuntu/Debian)

```bash
# Qt6 headless (instalado automaticamente pelo install.sh)
sudo apt-get install -y \
  libgl1 libglib2.0-0 libxkbcommon-x11-0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-randr0 libxcb-render-util0

# Tailscale (workflow-mobile)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```
