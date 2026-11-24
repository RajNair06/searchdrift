"""ORM models: one class per database table.

Every field matches its locked entity doc in docs/entities/. SQLAlchemy
translates these classes into CREATE TABLE statements that Alembic uses to
generate migrations.

Import order matters: models that are referenced by foreign keys from other
models don't need to be defined first — SQLAlchemy resolves string-based
ForeignKey references lazily. But we import them all here so that
alembic/env.py can see every table via Base.metadata.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from searchdrift.db import Base

# ---------------------------------------------------------------------------
# GoldSet — one version of the exam (v1, v2, …)
# ---------------------------------------------------------------------------


class GoldSet(Base):
    """A named, numbered collection of Questions.

    Draft GoldSets can be edited freely. Once frozen, nothing changes — ever.
    Every Run points at one frozen GoldSet, so two runs on the same GoldSet
    are comparable.
    """

    __tablename__ = "gold_sets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

    # Relationships
    questions: Mapped[list["Question"]] = relationship(
        back_populates="gold_set", cascade="all, delete-orphan"
    )
    runs: Mapped[list["Run"]] = relationship(back_populates="gold_set")

    __table_args__ = (
        CheckConstraint("version > 0", name="ck_gold_sets_version_positive"),
        # frozen ⟺ frozen_at is set
        CheckConstraint(
            "(status = 'frozen') = (frozen_at IS NOT NULL)",
            name="ck_gold_sets_frozen_at",
        ),
        # frozen ⟺ content_hash is set
        CheckConstraint(
            "(status = 'frozen') = (content_hash IS NOT NULL)",
            name="ck_gold_sets_content_hash",
        ),
    )


# ---------------------------------------------------------------------------
# Vendor — one search API we benchmark (tavily, exa, serper)
# ---------------------------------------------------------------------------


class Vendor(Base):
    """A search API vendor: identity, kill switch, and credit budget.

    Uses a natural key ('tavily') instead of a UUID because vendor names are
    short, global, and never change. This makes foreign key values readable
    in other tables without a join.
    """

    __tablename__ = "vendors"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # natural key: 'tavily'
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    budget_calls: Mapped[int] = mapped_column(Integer)
    budget_period: Mapped[str] = mapped_column(Text)  # 'monthly' or 'total'
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

    # Relationships
    trials: Mapped[list["Trial"]] = relationship(back_populates="vendor")
    cassettes: Mapped[list["Cassette"]] = relationship(back_populates="vendor")
    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="vendor")

    __table_args__ = (
        CheckConstraint("budget_calls >= 0", name="ck_vendors_budget_non_negative"),
        CheckConstraint(
            "budget_period IN ('monthly', 'total')",
            name="ck_vendors_budget_period",
        ),
    )


# ---------------------------------------------------------------------------
# Question — one item on the exam
# ---------------------------------------------------------------------------


class Question(Base):
    """One question with its gold answer and scoring rule.

    Belongs to exactly one GoldSet. The gold answer is stored as JSONB
    because its shape depends on the scoring_unit (entities vs urls),
    and it is always read as a whole — never queried per item.
    """

    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    gold_set_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("gold_sets.id", ondelete="CASCADE"),
    )
    key: Mapped[str] = mapped_column(Text)  # human-readable ID, e.g. 'python-creator'
    text: Mapped[str] = mapped_column(Text)
    scoring_unit: Mapped[str] = mapped_column(Text)  # 'entities' or 'urls'
    gold: Mapped[dict] = mapped_column(JSONB)
    verification: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

    # Relationships
    gold_set: Mapped["GoldSet"] = relationship(back_populates="questions")
    trials: Mapped[list["Trial"]] = relationship(back_populates="question")

    __table_args__ = (
        # Same key can't appear twice in one GoldSet.
        # Also creates an index starting with gold_set_id for fast lookups.
        UniqueConstraint("gold_set_id", "key", name="uq_questions_gold_set_key"),
        CheckConstraint(
            "scoring_unit IN ('entities', 'urls')",
            name="ck_questions_scoring_unit",
        ),
    )


# ---------------------------------------------------------------------------
# Run — one sitting of the exam
# ---------------------------------------------------------------------------


class Run(Base):
    """One measurement session: a frozen GoldSet given to N vendors, K results,
    R repeats.

    The API creates Runs and their Trials but never executes them — a separate
    runner process does the vendor calls. This is the control-plane /
    data-plane split.
    """

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    gold_set_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("gold_sets.id", ondelete="RESTRICT"),
    )
    config: Mapped[dict] = mapped_column(JSONB)
    code_version: Mapped[str] = mapped_column(Text)  # git SHA
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    gold_set: Mapped["GoldSet"] = relationship(back_populates="runs")
    trials: Mapped[list["Trial"]] = relationship(back_populates="run")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_runs_status",
        ),
    )


# ---------------------------------------------------------------------------
# Cassette — one recorded vendor call
# ---------------------------------------------------------------------------


class Cassette(Base):
    """One recorded vendor call: request, response, latency, timestamp.

    Append-only: a live call always inserts a new row. The same request_hash
    can appear many times (3 repeats in one run, nightly runs over weeks).
    Cassettes are never updated or deleted.
    """

    __tablename__ = "cassettes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("vendors.id", ondelete="RESTRICT"),
    )
    request_hash: Mapped[str] = mapped_column(Text, index=True)  # indexed, not unique
    request: Mapped[dict] = mapped_column(JSONB)  # method, URL, headers (no API key), body
    status_code: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[str] = mapped_column(Text)  # TEXT not JSONB: preserves exact bytes
    latency_ms: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

    # Relationships
    vendor: Mapped["Vendor"] = relationship(back_populates="cassettes")
    trials: Mapped[list["Trial"]] = relationship(back_populates="cassette")


# ---------------------------------------------------------------------------
# Trial — one question × one vendor × one repeat
# ---------------------------------------------------------------------------


class Trial(Base):
    """The smallest unit of work: one question asked to one vendor once.

    In Tier 1, one trial = exactly one vendor call. The trial links to the
    cassette (what the vendor said) and the question (what we asked).

    In week 3 this table becomes the job queue: workers claim pending trials
    with SELECT ... FOR UPDATE SKIP LOCKED.
    """

    __tablename__ = "trials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("runs.id", ondelete="RESTRICT"),
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("questions.id", ondelete="RESTRICT"),
    )
    vendor_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("vendors.id", ondelete="RESTRICT"),
    )
    repeat_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    cassette_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("cassettes.id", ondelete="RESTRICT"),
    )
    error_kind: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)

    # Relationships
    run: Mapped["Run"] = relationship(back_populates="trials")
    question: Mapped["Question"] = relationship(back_populates="trials")
    vendor: Mapped["Vendor"] = relationship(back_populates="trials")
    cassette: Mapped["Cassette | None"] = relationship(back_populates="trials")
    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="trial")

    __table_args__ = (
        # A run can never contain the same trial twice.
        UniqueConstraint(
            "run_id",
            "question_id",
            "vendor_id",
            "repeat_index",
            name="uq_trials_run_question_vendor_repeat",
        ),
        # Success always has evidence (a cassette).
        CheckConstraint(
            "status <> 'succeeded' OR cassette_id IS NOT NULL",
            name="ck_trials_succeeded_has_cassette",
        ),
        # Failed ⟺ has a failure category.
        CheckConstraint(
            "(status = 'failed') = (error_kind IS NOT NULL)",
            name="ck_trials_failed_has_error_kind",
        ),
        CheckConstraint(
            "repeat_index >= 1",
            name="ck_trials_repeat_positive",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')",
            name="ck_trials_status",
        ),
        CheckConstraint(
            "error_kind IN ('timeout', 'http_error', 'parse_error', 'replay_miss')",
            name="ck_trials_error_kind",
        ),
    )


# ---------------------------------------------------------------------------
# LedgerEntry — one live vendor call, written in the books
# ---------------------------------------------------------------------------


class LedgerEntry(Base):
    """One credit reservation for a live vendor call.

    Created BEFORE the call (reserve), resolved AFTER it (settled / released /
    uncertain). Replay runs never touch the ledger — replay is free.

    The four states handle the hard case: a call that timed out, where we
    can't know if the vendor charged us. 'uncertain' counts it (safe direction).
    """

    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("vendors.id", ondelete="RESTRICT"),
    )
    trial_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("trials.id", ondelete="RESTRICT"),
    )
    state: Mapped[str] = mapped_column(Text, server_default="reserved")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    vendor: Mapped["Vendor"] = relationship(back_populates="ledger_entries")
    trial: Mapped["Trial"] = relationship(back_populates="ledger_entries")

    __table_args__ = (
        # One entry per trial (becomes per trial+attempt in week 3).
        UniqueConstraint("trial_id", name="uq_ledger_entries_trial"),
        # reserved ⟺ not yet resolved.
        CheckConstraint(
            "(state = 'reserved') = (resolved_at IS NULL)",
            name="ck_ledger_entries_reserved_resolved",
        ),
        CheckConstraint(
            "state IN ('reserved', 'settled', 'released', 'uncertain')",
            name="ck_ledger_entries_state",
        ),
        # Budget checks count one vendor's entries in a period — this index
        # makes that fast.
        Index("ix_ledger_entries_vendor_created", "vendor_id", "created_at"),
    )
