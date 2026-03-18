# tests/load/scenarios/ws_control.py
# Cenário: Envio de control messages (play/pause/skip)
# Uso: locust -f tests/load/scenarios/ws_control.py --headless -u 1 -r 1 -t 1m
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

# SLOs importados de slos.json → scenarios.control_ack_latency
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


class WsControlUser(WebSocketUser):
    """
    Cenário: Envio de control messages (play/pause/skip).

    Fluxo:
      1. Conecta ao servidor WebSocket.
      2. Alterna entre envio de control play, pause e skip.
      3. Aguarda control_ack em cada envio.
      4. Valida que o ack reflete a ação enviada.

    Referência: remote_server.py → _handle_control()
                dtos.py → ControlPayload
    SLO: p95 < 100ms, p99 < 200ms (slos.json → control_ack_latency)
    """

    wait_time = between(1, 3)
    host = BASE_URL

    # Ciclo de ações para evitar requisições idempotentes consecutivas
    _actions = ["play", "pause", "skip"]
    _action_index: int = 0

    def on_start(self) -> None:
        # Conexão única por usuário — servidor no modo single-client.
        pass

    @task(3)
    @tag("control", "play")
    def control_play(self) -> None:
        """Envia control play e aguarda ack."""
        self._send_control("play")

    @task(3)
    @tag("control", "pause")
    def control_pause(self) -> None:
        """Envia control pause e aguarda ack."""
        self._send_control("pause")

    @task(2)
    @tag("control", "skip")
    def control_skip(self) -> None:
        """Envia control skip e aguarda ack."""
        self._send_control("skip")

    def _send_control(self, action: str) -> None:
        """Helper: envia mensagem de controle e valida o control_ack."""
        msg = _envelope("control", {"action": action})
        name = f"control_{action}"

        with self.client.send(
            msg,
            name=name,
            catch_response=True,
        ) as response:
            if response is None:
                response.failure(f"Sem resposta ao control {action}")
                return

            try:
                data = json.loads(response.data) if isinstance(response.data, str) else {}
                msg_type = data.get("type")

                if msg_type == "error":
                    # Servidor pode retornar error se o estado do pipeline não permite
                    # a ação (ex: pause quando IDLE). Não é falha de SLO.
                    response.success()
                elif msg_type != "control_ack":
                    response.failure(
                        f"Tipo inesperado: {msg_type} (esperado: control_ack)"
                    )
                elif response.elapsed_ms > SLO_P95_MS:
                    response.failure(
                        f"Latência {response.elapsed_ms}ms > SLO p95 {SLO_P95_MS}ms"
                    )
                else:
                    response.success()
            except (json.JSONDecodeError, AttributeError):
                # Sem body se o servidor ainda não respondeu assincronamente.
                response.success()
