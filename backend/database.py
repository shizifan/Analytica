from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import (
    BigInteger, Column, String, JSON, DateTime, Integer, Float, Text, SmallInteger,
    UniqueConstraint, Index, func,
)


class Base(DeclarativeBase):
    pass


class SessionModel(Base):
    __tablename__ = "sessions"

    session_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=False, index=True)
    employee_id = Column(String(100), nullable=True, index=True)
    state_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Rail metadata for HistoryPane (Phase 2)
    title = Column(String(255), nullable=True)
    pinned = Column(SmallInteger, nullable=False, server_default="0")
    deleted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_sessions_user_updated", "user_id", "updated_at"),
    )


class ChatMessageModel(Base):
    """Display-projection of conversation messages (Phase 2).

    Written in parallel with state_json.messages — not the primary source
    of truth for graph logic, but the authoritative source for replay and
    the HistoryPane UI.
    """

    __tablename__ = "chat_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String(36), nullable=False)
    role = Column(String(16), nullable=False)  # user / assistant / system
    type = Column(String(32), nullable=False, server_default="text")
    phase = Column(String(32), nullable=True)
    content = Column(Text, nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_chat_messages_session_id", "session_id", "id"),
    )


class EmployeeModel(Base):
    """Digital-worker profile (Phase 4).

    Superset of the YAML schema plus `initials` / `faqs` / `status`
    columns that power the admin drawer. Endpoints = [] retains the
    legacy "auto-derive from domains" semantic.
    """

    __tablename__ = "employees"

    employee_id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    version = Column(String(32), nullable=False, server_default="1.0")
    initials = Column(String(8), nullable=True)
    status = Column(String(16), nullable=False, server_default="active")
    domains = Column(JSON, nullable=False)
    endpoints = Column(JSON, nullable=False)
    tools = Column(JSON, nullable=False)
    faqs = Column(JSON, nullable=False)
    perception = Column(JSON, nullable=True)
    planning = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(),
    )


class EmployeeVersionModel(Base):
    """Frozen snapshots of an employee profile for audit / diff / rollback."""

    __tablename__ = "employee_versions"

    employee_id = Column(String(64), primary_key=True)
    version = Column(String(32), primary_key=True)
    snapshot = Column(JSON, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class ReportArtifactModel(Base):
    """Generated report file (HTML / DOCX / PPTX / Markdown) — Phase 5.

    The bytes live on disk under `settings.REPORTS_DIR` to keep MySQL
    slim; this row is the lookup key + metadata for the download /
    preview endpoints.
    """

    __tablename__ = "report_artifacts"

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), nullable=False)
    task_id = Column(String(64), nullable=True)
    tool_id = Column(String(100), nullable=True)
    format = Column(String(16), nullable=False)
    title = Column(String(255), nullable=True)
    file_path = Column(String(512), nullable=False)
    size_bytes = Column(BigInteger, nullable=True)
    status = Column(String(16), nullable=False, server_default="ready")
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_report_artifacts_session", "session_id", "created_at"),
    )


class ThinkingEventModel(Base):
    """Agent thinking / tool-call / decision audit trail (Phase 2).

    Feeds the "思维流" tab of Agent Inspector. Append-only; never mutated.
    """

    __tablename__ = "thinking_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String(36), nullable=False)
    kind = Column(String(16), nullable=False)  # thinking / tool / decision / phase
    phase = Column(String(32), nullable=True)
    ts_ms = Column(BigInteger, nullable=False)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_thinking_events_session_id", "session_id", "id"),
    )


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=False)
    key = Column(String(255), nullable=False)
    value = Column(JSON, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_pref_key"),
    )


class AnalysisTemplate(Base):
    __tablename__ = "analysis_templates"

    template_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=False)
    name = Column(Text, nullable=False)
    domain = Column(String(100), nullable=True)
    output_complexity = Column(String(50), nullable=True)
    tags = Column(JSON, nullable=True)
    plan_skeleton = Column(JSON, nullable=True)
    usage_count = Column(Integer, default=0)
    last_used = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_templates_lookup", "user_id", "domain", "output_complexity"),
    )


class ToolNote(Base):
    __tablename__ = "tool_notes"

    id = Column(String(36), primary_key=True)
    tool_id = Column(String(100), nullable=False)
    user_id = Column(String(36), nullable=False)
    notes = Column(Text, nullable=True)
    performance_score = Column(Float, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tool_id", "user_id", name="uq_tool_user"),
    )


class SlotHistory(Base):
    __tablename__ = "slot_history"

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), nullable=False, index=True)
    slot_name = Column(String(100), nullable=False)
    value = Column(JSON, nullable=True)
    source = Column(String(50), nullable=True)
    was_corrected = Column(SmallInteger, default=0)
    round_num = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


_engine = None
_session_factory = None


def get_engine(database_url: str | None = None):
    """Get or create the async engine."""
    global _engine
    if _engine is None:
        if database_url is None:
            from backend.config import get_settings
            database_url = get_settings().DATABASE_URL
        _engine = create_async_engine(
            database_url,
            pool_size=10,
            max_overflow=20,
            pool_recycle=3600,
            echo=False,
        )
    return _engine


def get_session_factory(database_url: str | None = None) -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine(database_url)
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _session_factory


async def get_db_session() -> AsyncSession:
    """FastAPI dependency: yield an async database session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session
