# tests/load/locustfile.py
# Orquestrador Locust — importa todos os cenários WebSocket
#
# Uso (todos os cenários):
#   locust -f tests/load/locustfile.py
#   locust -f tests/load/locustfile.py --headless -u 1 -r 1 -t 1m
#
# Uso (cenário individual):
#   locust -f tests/load/scenarios/ws_connect_sync.py --headless -u 1 -r 1 -t 1m
#   locust -f tests/load/scenarios/ws_control.py      --headless -u 1 -r 1 -t 1m
#   locust -f tests/load/scenarios/ws_interaction.py  --headless -u 1 -r 1 -t 1m
#
# Pré-requisito: pip install locust locust-plugins
# ATENÇÃO: O servidor aceita apenas IPs Tailscale (100.64.0.0/10) e
#          opera em modo single-client (apenas 1 conexão simultânea).
#          Para testes multi-usuário, o segundo usuário receberá close 1008.
#
# Cenários disponíveis:
#   WsConnectSyncUser    — sync_request baseline (SLO: p95 < 100ms)
#   WsControlUser        — control play/pause/skip (SLO: p95 < 100ms)
#   WsInteractionUser    — interaction_response (SLO: ceiling < 500ms)

from scenarios.ws_connect_sync import WsConnectSyncUser  # noqa: F401
from scenarios.ws_control import WsControlUser  # noqa: F401
from scenarios.ws_interaction import WsInteractionUser  # noqa: F401

# Locust auto-descobre todas as classes WebSocketUser/HttpUser importadas.
# Para limitar a um cenário específico, use -f diretamente no arquivo do cenário
# ou passe --tags para filtrar por tag.
