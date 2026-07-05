"""
AppState — Estado global mutável da aplicação (módulo-03/TASK-2).

Mantém os PipelineConfig atualmente carregados, separados em slots tipados
por anexo (project e loop). Acesso via singleton:
    from workflow_app.config.app_state import app_state

Não use diretamente em widgets — prefira signals do SignalBus
para reagir a mudanças de estado.

Precedência / fonte da verdade
------------------------------
Os slots tipados ``project_config`` e ``loop_config`` são a FONTE DA VERDADE
do estado de anexos. A facade legada ``config``/``has_config``/``set_config``/
``clear_config`` é DERIVADA desses slots: ``config`` lê o slot de project quando
presente e cai para o slot de loop caso contrário, nunca é escrita diretamente
por código novo (apenas leitura de compatibilidade temporária). Em qualquer
divergência os slots tipados vencem. Código novo deve usar
``set_project_config``/``set_loop_config`` e ``clear_project``/``clear_loop``;
``set_config``/``clear_config`` permanecem como alias de compatibilidade
enquanto os consumidores são migrados (itens 003/004 do loop).
"""

from __future__ import annotations

from workflow_app.config.config_parser import PipelineConfig


class AppState:
    """Estado mutable global da aplicação (não é QObject).

    Mantém referências tipadas aos PipelineConfig de project e de loop em
    slots independentes. O slot de project nunca é apagado por carregar/limpar
    o slot de loop e vice-versa (clear granular). A facade legada ``config`` é
    derivada desses slots (ver docstring do módulo).
    """

    def __init__(self) -> None:
        self._project_config: PipelineConfig | None = None
        self._loop_config: PipelineConfig | None = None
        self._loop_mode: str | None = None

    # ------------------------------------------------------------------
    # Slots tipados (fonte da verdade)
    # ------------------------------------------------------------------
    @property
    def project_config(self) -> PipelineConfig | None:
        return self._project_config

    @property
    def loop_config(self) -> PipelineConfig | None:
        return self._loop_config

    @property
    def has_project(self) -> bool:
        return self._project_config is not None

    @property
    def has_loop(self) -> bool:
        return self._loop_config is not None

    def set_project_config(self, config: PipelineConfig) -> None:
        """Carrega o config de project no slot tipado (não toca o loop)."""
        self._project_config = config

    def set_loop_config(self, config: PipelineConfig) -> None:
        """Carrega o config de loop no slot tipado (não toca o project)."""
        self._loop_config = config

    def clear_project(self) -> None:
        """Limpa apenas o slot de project; preserva o slot de loop."""
        self._project_config = None

    def clear_loop(self) -> None:
        """Limpa apenas o slot de loop (e o loop_mode); preserva o project."""
        self._loop_config = None
        self._loop_mode = None

    def clear_all(self) -> None:
        """Retorna o estado ao empty state inicial (idêntico a ``AppState()``).

        Após esta chamada ``has_project`` e ``has_loop`` ficam ``False``, os
        slots tipados ficam ``None`` e a facade legada ``config`` volta ao
        default (``None``). Equivale, por igualdade canônica, a um
        ``AppState()`` recém-inicializado.
        """
        self._project_config = None
        self._loop_config = None
        self._loop_mode = None

    # ------------------------------------------------------------------
    # Facade legada (derivada — leitura de compatibilidade temporária)
    # ------------------------------------------------------------------
    @property
    def config(self) -> PipelineConfig | None:
        """Config ativo derivado: project quando presente, senão loop.

        Compatibilidade temporária — não escrever diretamente em código novo.
        """
        if self._project_config is not None:
            return self._project_config
        return self._loop_config

    @property
    def has_config(self) -> bool:
        return self.config is not None

    def set_config(self, config: PipelineConfig) -> None:
        """Alias legado de ``set_project_config`` (compatibilidade)."""
        self._project_config = config

    def clear_config(self) -> None:
        """Alias legado: limpa todo o estado global (equivale a ``clear_all``)."""
        self.clear_all()

    @property
    def project_name(self) -> str:
        cfg = self.config
        if cfg:
            return cfg.project_name
        return ""

    @property
    def loop_mode(self) -> str | None:
        return self._loop_mode

    def set_loop_mode(self, mode: str | None) -> None:
        self._loop_mode = mode

    # ------------------------------------------------------------------
    # Igualdade por valor (empty state / comparação canônica)
    # ------------------------------------------------------------------
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AppState):
            return NotImplemented
        return (
            self._project_config == other._project_config
            and self._loop_config == other._loop_config
            and self._loop_mode == other._loop_mode
        )

    def __hash__(self) -> int:
        """Hash consistente com ``__eq__`` (contrato a == b => hash(a) == hash(b)).

        Os ``PipelineConfig`` são dataclasses ``eq=True`` não-frozen, logo
        unhashable; por isso o hash deriva apenas dos discriminantes de
        presença/modo (``has_project``, ``has_loop``, ``_loop_mode``). Estados
        iguais por valor têm necessariamente esses três discriminantes iguais,
        então o hash bate; colisões entre estados distintos são permitidas pelo
        contrato. Mantém o singleton utilizável como chave/elemento de set sem
        violar a invariante hash/eq.
        """
        return hash((self.has_project, self.has_loop, self._loop_mode))


# Singleton
app_state = AppState()
