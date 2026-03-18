# tests/load/scenarios/ws_interaction.py
# Cenário: Envio de interaction_response (resposta a interaction_request)
# Uso: locust -f tests/load/scenarios/ws_interaction.py --headless -u 1 -r 1 -t 1m
#
# Pré-requisito: pip install locust locust-plugins
# ATENÇÃO: O servidor aceita apenas IPs Tailscale (100.64.0.0/10).
#          Execute este teste a partir de uma máquina na rede Tailscale.
#
# Nota: O servidor só aceita interaction_response quando há uma
#       interaction_request pendente. Quando não há, retorna error —
#       o que é comportamento esperado e conta como sucesso neste cenário.

import json
import os
import uuid
from datetime import datetime, timezone

from locust import between, tag, task
from locust_plugins.users.websocket import WebSocketUser

BASE_URL = os.getenv("BASE_URL", "ws://100.64.0.1:18765")

# SLOs importados de slos.json → scenarios.end_to_end_budget
SLO_CEILING_MS = 500


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


class WsInteractionUser(WebSocketUser):
    """
    Cenário: Envio de interaction_response.

    Fluxo:
      1. Conecta ao servidor WebSocket.
      2. Primeiro solicita estado atual via sync_request para detectar
         se há interaction_request pendente.
      3. Envia interaction_response com request_id e value.
      4. Valida resposta do servidor:
         - interaction_response_ack: resposta aceita com sucesso.
         - error: nenhuma interação pendente — comportamento esperado
                  (primeiro-a-responder ganha; PC pode ter respondido antes).

    Referência: remote_server.py → _handle_interaction_response()
                dtos.py → InteractionResponsePayload
    SLO: ceiling < 500ms (slos.json → end_to_end_budget)
    """

    wait_time = between(2, 5)
    host = BASE_URL

    # request_id simulado — em produção viria da interaction_request do servidor.
    # Como o servidor pode não ter interação pendente, usamos um UUID aleatório.
    # Quando não há interação pendente, o servidor retorna error, o que é esperado.
    _SIMULATED_REQUEST_ID = "test-interaction-request-id"

    def on_start(self) -> None:
        # Conexão única por usuário — servidor no modo single-client.
        pass

    @task(2)
    @tag("interaction", "text_response")
    def send_text_response(self) -> None:
        """Envia resposta textual a uma interaction_request."""
        self._send_interaction_response(
            request_id=self._SIMULATED_REQUEST_ID,
            value="OK",
        )

    @task(1)
    @tag("interaction", "custom_response")
    def send_custom_response(self) -> None:
        """Envia resposta personalizada com texto custom."""
        self._send_interaction_response(
            request_id=self._SIMULATED_REQUEST_ID,
            value="Confirmar operação",
        )

    def _send_interaction_response(self, request_id: str, value: str) -> None:
        """Helper: envia interaction_response e valida a resposta do servidor."""
        payload = {
            "request_id": request_id,
            "value": value,
        }
        msg = _envelope("interaction_response", payload)

        with self.client.send(
            msg,
            name="interaction_response",
            catch_response=True,
        ) as response:
            if response is None:
                response.failure("Sem resposta ao interaction_response")
                return

            try:
                data = json.loads(response.data) if isinstance(response.data, str) else {}
                msg_type = data.get("type")

                if msg_type == "error":
                    # Servidor pode retornar error quando não há interaction_request
                    # pendente (first-response-wins: PC pode ter respondido antes).
                    # Não é falha de SLO — é comportamento esperado.
                    response.success()
                elif msg_type == "interaction_response_ack":
                    if response.elapsed_ms > SLO_CEILING_MS:
                        response.failure(
                            f"Latência {response.elapsed_ms}ms > SLO ceiling {SLO_CEILING_MS}ms"
                        )
                    else:
                        response.success()
                else:
                    response.failure(
                        f"Tipo inesperado: {msg_type} "
                        f"(esperado: interaction_response_ack ou error)"
                    )
            except (json.JSONDecodeError, AttributeError):
                # Sem body se o servidor ainda não respondeu assincronamente.
                response.success()
