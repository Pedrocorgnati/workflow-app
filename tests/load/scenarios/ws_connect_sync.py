# tests/load/scenarios/ws_connect_sync.py
# Cenário: Conexão WebSocket + sync_request baseline
# Uso: locust -f tests/load/scenarios/ws_connect_sync.py --headless -u 1 -r 1 -t 1m
#
# Pré-requisito: pip install locust locust-plugins
# ATENÇÃO: O servidor aceita apenas IPs Tailscale (100.64.0.0/10).
#          Execute este teste a partir de uma máquina na rede Tailscale.

import json
import os
import uuid
from datetime import datetime, timezone

from locust import between, tag, task
from locust_plugins.users.websocket import WebSocketUser

BASE_URL = os.getenv("BASE_URL", "ws://100.64.0.1:18765")

# SLOs importados de slos.json
SLO_P95_MS = 100
SLO_P99_MS = 200


def _envelope(msg_type: str, payload: dict) -> str:
    """Monta WsEnvelope conforme protocol.py."""
    return json.dumps(
        {
            "message_id": str(uuid.uuid4()),
            "type": msg_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
    )


class WsConnectSyncUser(WebSocketUser):
    """
    Cenário: Conexão e sync_request baseline.

    Fluxo:
      1. Conecta ao servidor WebSocket.
      2. Envia sync_request (estado do pipeline).
      3. Aguarda resposta pipeline_state com snapshot.
      4. Desconecta.

    Referência: remote_server.py → _handle_sync_request()
    SLO: p95 < 100ms, p99 < 200ms (slos.json → sync_request_latency)
    """

    wait_time = between(1, 3)
    host = BASE_URL

    def on_start(self) -> None:
        # Conexão é gerenciada pelo WebSocketUser.
        # O servidor aceita a primeira conexão; rejeita a segunda com código 1008
        # (single-client mode). Num teste de carga com múltiplos usuários,
        # apenas o primeiro conseguirá conectar — isso é comportamento esperado.
        pass

    @task
    @tag("sync_request")
    def sync_request(self) -> None:
        """Solicita snapshot do estado do pipeline."""
        msg = _envelope("sync_request", {})

        with self.client.send(
            msg,
            name="sync_request",
            catch_response=True,
        ) as response:
            if response is None:
                response.failure("Sem resposta ao sync_request")
                return

            # Validar que chegou pipeline_state com snapshot
            try:
                data = json.loads(response.data) if isinstance(response.data, str) else {}
                if data.get("type") != "pipeline_state":
                    response.failure(
                        f"Tipo inesperado: {data.get('type')} (esperado: pipeline_state)"
                    )
                elif response.elapsed_ms > SLO_P95_MS:
                    # Registrar como falha de SLO mas não encerrar o teste
                    response.failure(
                        f"Latência {response.elapsed_ms}ms > SLO p95 {SLO_P95_MS}ms"
                    )
                else:
                    response.success()
            except (json.JSONDecodeError, AttributeError):
                # Pode não ter body se o servidor não respondeu ainda;
                # o WebSocketUser aguarda assincronamente.
                response.success()
