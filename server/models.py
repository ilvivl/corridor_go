"""ORM-модели слоя данных (этап 2): партии и история ходов.

Форма JSONB-колонок — контракт с ядром ``game/``:
- ``Game.state``  = ``GameState.to_json()``  (источник истины, ``turn`` внутри)
- ``Move.action`` = ``action_to_json(action)``
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    SmallInteger,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.db import Base


class Game(Base):
    """Партия. ``state`` (JSONB) — источник истины: фишки, стены, ``turn``.
    ``winner`` и ``ply`` продублированы колонками — для лобби и защиты от гонок.
    ``mode``/``turn`` отдельными колонками НЕ держим (ИИ вне MVP; turn в state)."""

    __tablename__ = "games"
    __table_args__ = (
        CheckConstraint(
            "status IN ('waiting', 'active', 'finished', 'abandoned')",
            name="ck_games_status",
        ),
    )

    # uuid4 генерим в Python до вставки — чтобы сразу отдать ссылку-приглашение.
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    status: Mapped[str] = mapped_column(default="waiting")
    private: Mapped[bool] = mapped_column(default=False)
    # КОНТРАКТ ЗАПИСИ: state ВСЕГДА переприсваивать целиком —
    #     game.state = new_state.to_json()
    # SQLAlchemy не отслеживает мутации JSONB «на месте» (особенно вложенные:
    # state["pawns"][...] = ...) — такой UPDATE молча не уйдёт = потерянный ход.
    # Ядро и так возвращает новый GameState из apply(), так что реассайн — естественный путь.
    state: Mapped[dict] = mapped_column(JSONB)
    # Секреты: клиенту НИКОГДА не отдаём (ни в лобби, ни в публичном состоянии).
    player1_token: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), default=uuid.uuid4,
    )
    player2_token: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), default=None,
    )
    ply: Mapped[int] = mapped_column(SmallInteger, default=0)
    winner: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    moves: Mapped[list["Move"]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Move.ply",
    )

    def __repr__(self) -> str:  # удобство ручного смоука
        return f"<Game {self.id} status={self.status} ply={self.ply}>"


class Move(Base):
    """Один полуход (история для реплея/отладки). ``UNIQUE(game_id, ply)`` —
    фундамент защиты от дублей и гонок на этапе realtime."""

    __tablename__ = "moves"
    __table_args__ = (
        UniqueConstraint("game_id", "ply", name="uq_moves_game_ply"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # bigserial
    game_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="CASCADE"),
        index=True,
    )
    ply: Mapped[int] = mapped_column(SmallInteger)  # как Game.ply
    player: Mapped[int] = mapped_column(SmallInteger)
    action: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    game: Mapped["Game"] = relationship(back_populates="moves")

    def __repr__(self) -> str:
        return f"<Move game={self.game_id} ply={self.ply} player={self.player}>"
