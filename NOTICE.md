# NOTICE — Atribuições de Software de Terceiros

**Projeto:** workflow-app
**Gerado em:** 2026-03-16
**Versão:** 0.1.0

Este projeto utiliza os seguintes componentes de software de terceiros:

---

## Licenças Permissivas (MIT, BSD, Apache, PSF)

| Pacote | Versão | Licença | Uso |
|--------|--------|---------|-----|
| SQLAlchemy | 2.0.48 | MIT | produção |
| alembic | 1.18.4 | MIT | produção |
| anyio | 4.12.1 | MIT | produção |
| attrs | 25.4.0 | MIT | produção |
| cffi | 2.0.0 | MIT | produção |
| claude-agent-sdk | 0.1.48 | MIT | produção |
| click | 8.3.1 | BSD-3-Clause | produção |
| cryptography | 46.0.5 | Apache-2.0 OR BSD-3-Clause | produção |
| greenlet | 3.3.2 | MIT AND PSF-2.0 | produção |
| h11 | 0.16.0 | MIT | produção |
| httpcore | 1.0.9 | BSD-3-Clause | produção |
| httpx | 0.28.1 | BSD-3-Clause | produção |
| httpx-sse | 0.4.3 | MIT | produção |
| idna | 3.11 | BSD-3-Clause | produção |
| jsonschema | 4.26.0 | MIT | produção |
| jsonschema-specifications | 2025.9.1 | MIT | produção |
| librt | 0.8.1 | MIT | produção |
| Mako | 1.3.10 | MIT | produção |
| MarkupSafe | 3.0.3 | BSD-3-Clause | produção |
| mcp | 1.26.0 | MIT | produção |
| packaging | 26.0 | Apache-2.0 OR BSD-2-Clause | produção |
| pycparser | 3.0 | BSD-3-Clause | produção |
| pydantic | 2.12.5 | MIT | produção |
| pydantic-core | 2.41.5 | MIT | produção |
| pydantic-settings | 2.13.1 | MIT | produção |
| Pygments | 2.19.2 | BSD-2-Clause | produção |
| python-multipart | 0.0.22 | Apache-2.0 | produção |
| python-statemachine | 3.0.0 | MIT | produção |
| referencing | 0.37.0 | MIT | produção |
| sse-starlette | 3.3.2 | BSD-3-Clause | produção |
| starlette | 0.52.1 | BSD-3-Clause | produção |
| typing-extensions | 4.15.0 | PSF-2.0 | produção |
| typing-inspection | 0.4.2 | MIT | produção |
| uvicorn | 0.41.0 | BSD-3-Clause | produção |
| wcwidth | 0.6.0 | MIT | produção |
| annotated-types | 0.7.0 | MIT* | produção |
| pathspec | 1.0.4 | MPL-2.0* | produção |
| ruff | 0.15.5 | MIT* | dev |
| mypy | 1.19.1 | MIT | dev |
| mypy-extensions | 1.1.0 | MIT | dev |
| pluggy | 1.6.0 | MIT | dev |
| pytest | 9.0.2 | MIT | dev |
| pytest-qt | 4.5.0 | MIT | dev |
| pytest-timeout | 2.4.0 | MIT | dev |
| iniconfig | 2.3.0 | MIT | dev |

*Licença inferida por análise do repositório — campo License ausente nos metadados PyPI.

---

## Licenças LGPL / MPL (Copyleft Fraco)

| Pacote | Versão | Licença | Observação |
|--------|--------|---------|------------|
| PySide6 | 6.10.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Framework de UI. Uso sob LGPL-3.0 — ver nota. |
| PySide6-Addons | 6.10.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Módulos adicionais PySide6. Mesma licença. |
| PySide6-Essentials | 6.10.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Módulos essenciais PySide6. Mesma licença. |
| shiboken6 | 6.10.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Runtime binding do PySide6. Mesma licença. |
| certifi | 2026.2.25 | MPL-2.0 | Modificações ao certifi devem ser abertas. |
| pyte | 0.8.2 | LGPL-3.0* | Emulador de terminal. Uso sem modificação: ok. |

### Nota sobre PySide6 (LGPL-3.0)

O workflow-app usa o Qt for Python (PySide6) sob a licença **LGPL-3.0**. A escolha LGPL
é aplicável porque:

1. O PySide6 é linkado **dinamicamente** — usuários podem substituir a biblioteca PySide6
   por uma versão modificada sem acesso ao código-fonte do workflow-app.
2. A distribuição inclui a notificação desta licença (este arquivo NOTICE.md).
3. O código-fonte do projeto **não é GPL** — a LGPL não contamina código proprietário
   quando usado desta forma em aplicações desktop.

Para distribuição do workflow-app:
- Incluir este NOTICE.md
- Incluir o texto da LGPL-3.0: https://www.gnu.org/licenses/lgpl-3.0.txt
- Garantir que o usuário possa substituir PySide6 por relinkar o binário

---

*Gerado automaticamente por /dependency-audit. Revisar antes de distribuição pública.*
