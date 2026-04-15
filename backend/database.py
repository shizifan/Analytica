from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import (
    Column, String, JSON, DateTime, Integer, Float, Text, SmallInteger,
    UniqueConstraint, Index, func,
)


class Base(DeclarativeBase):
    pass


class SessionModel(Base):
    __tablename__ = "sessions"

    session_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=False, index=True)
    state_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


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


class SkillNote(Base):
    __tablename__ = "skill_notes"

    id = Column(String(36), primary_key=True)
    skill_id = Column(String(100), nullable=False)
    user_id = Column(String(36), nullable=False)
    notes = Column(Text, nullable=True)
    performance_score = Column(Float, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("skill_id", "user_id", name="uq_skill_user"),
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
