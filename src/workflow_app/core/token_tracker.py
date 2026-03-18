"""
TokenTracker — Conta tokens de entrada/saída e calcula custo por comando (module-15/TASK-1).

Persiste diretamente nos campos tokens_input/tokens_output/cost_usd do
CommandExecution. Usa preços configuráveis (fallback para _DEFAULT_PRICES).
"""

from __future__ import annotations

from workflow_app.db.database_manager import DatabaseManager
from workflow_app.domain import ModelType

# Preços padrão por 1M tokens (input_price_per_m, output_price_per_m) em USD
_DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    ModelType.OPUS.value:   (15.0,  75.0),
    ModelType.SONNET.value: (3.0,   15.0),
    ModelType.HAIKU.value:  (0.25,  1.25),
}


class TokenTracker:
    """Rastreia tokens de entrada/saída e custo estimado por comando.

    Persiste diretamente no campo tokens_input/tokens_output/cost_usd do
    CommandExecution. Usa preços configuráveis via AppConfig (fallback
    para _DEFAULT_PRICES se não configurados).
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        custom_prices: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        """
        Args:
            db_manager: gerenciador de banco de dados.
            custom_prices: dict {model_value: (price_in_per_m, price_out_per_m)}.
                           Sobrescreve os preços padrão. None = usar padrão.
        """
        self._db = db_manager
        self._prices = {**_DEFAULT_PRICES, **(custom_prices or {})}

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def record(
        self,
        command_id: int,
        tokens_in: int,
        tokens_out: int,
        model: ModelType,
    ) -> float:
        """Persiste tokens no CommandExecution e retorna custo estimado em USD.

        Args:
            command_id: ID do CommandExecution.
            tokens_in: tokens de entrada (prompt).
            tokens_out: tokens de saída (completion).
            model: ModelType usado no comando.

        Returns:
            Custo estimado em USD para este comando.
        """
        cost = self._calculate_cost(tokens_in, tokens_out, model)

        with self._db.get_session() as session:
            from workflow_app.db.models import CommandExecution
            cmd = session.get(CommandExecution, command_id)
            if cmd is not None:
                cmd.tokens_input = (cmd.tokens_input or 0) + tokens_in
                cmd.tokens_output = (cmd.tokens_output or 0) + tokens_out
                # Note: cost_usd lives on PipelineExecution, not CommandExecution.
                # Accumulate on pipeline level via get_session_total().

        return cost

    def get_session_total(
        self, pipeline_id: int
    ) -> tuple[int, int, float]:
        """Calcula totais de tokens e custo para um pipeline inteiro.

        Args:
            pipeline_id: ID do PipelineExecution.

        Returns:
            Tupla (tokens_input_total, tokens_output_total, cost_usd_total).
        """
        with self._db.get_session() as session:
            from workflow_app.db.models import CommandExecution
            commands = (
                session.query(CommandExecution)
                .filter(CommandExecution.pipeline_id == pipeline_id)
                .all()
            )

            total_in = sum((c.tokens_input or 0) for c in commands)
            total_out = sum((c.tokens_output or 0) for c in commands)
            total_cost = sum((c.cost_usd or 0.0) for c in commands)

        return total_in, total_out, total_cost

    def persist_pipeline_totals(self, pipeline_id: int) -> None:
        """Persist aggregated token totals and cost on PipelineExecution."""
        total_in, total_out, total_cost = self.get_session_total(pipeline_id)
        with self._db.get_session() as session:
            from workflow_app.db.models import PipelineExecution
            pe = session.get(PipelineExecution, pipeline_id)
            if pe is not None:
                pe.tokens_input = total_in
                pe.tokens_output = total_out
                pe.cost_usd = total_cost

    # ------------------------------------------------------------------
    # Cálculo interno
    # ------------------------------------------------------------------

    def _calculate_cost(
        self, tokens_in: int, tokens_out: int, model: ModelType
    ) -> float:
        """Calcula custo em USD baseado no modelo e na tabela de preços."""
        model_key = model.value if isinstance(model, ModelType) else str(model)
        price_in, price_out = self._prices.get(
            model_key, (3.0, 15.0)  # fallback para preço do sonnet
        )
        cost = (tokens_in * price_in + tokens_out * price_out) / 1_000_000
        return round(cost, 6)

    def update_prices(self, new_prices: dict[str, tuple[float, float]]) -> None:
        """Atualiza a tabela de preços em runtime (p.ex. após mudança no AppConfig)."""
        self._prices.update(new_prices)

    @staticmethod
    def format_cost(cost_usd: float) -> str:
        """Formata custo para exibição humana."""
        if cost_usd < 0.01:
            return f"${cost_usd:.4f}"
        return f"${cost_usd:.2f}"
