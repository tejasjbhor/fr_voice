"""
core/models.py — SQLAlchemy ORM models (Alembic source of truth)
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str] = mapped_column(String(16), default="mr-IN")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    family_contact: Mapped[str | None] = mapped_column(String(32), nullable=True)
    family_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    call_time: Mapped[str] = mapped_column(String(8), default="09:00")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # subscriber = family member who pays / adds people; user = elder who is called
    account_role: Mapped[str] = mapped_column(String(16), default="user")
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    has_smartphone: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    # ISO weekdays 1=Mon … 7=Sun
    days_of_week: Mapped[str] = mapped_column(String(32), default="1,2,3,4,5,6,7")
    last_scheduled_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    skip_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    consent_calls: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_recording: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_health: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_status: Mapped[str] = mapped_column(String(32), default="none")
    plan_activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Subscriber shares this code/link so the elder can open the app as User.
    invite_code: Mapped[str | None] = mapped_column(
        String(16), nullable=True, unique=True, index=True
    )
    invite_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversations = relationship("Conversation", back_populates="user")
    health_records = relationship("HealthRecord", back_populates="user")
    alerts = relationship("Alert", back_populates="user")
    api_costs = relationship("ApiCost", back_populates="user")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    audio_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Which language pack and which version of its prompt produced this turn.
    #
    # Both are recorded on the row rather than derived at read time. users.language
    # is mutable and reflects the caller's language NOW, so a user who switches
    # from Marathi to Hindi silently relabels every historical turn they ever had;
    # and without prompt_version no measured change in reply quality can be
    # attributed to any particular prompt edit. Nullable because rows written
    # before this column existed genuinely do not know.
    language: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user = relationship("User", back_populates="conversations")


class HealthRecord(Base):
    __tablename__ = "health_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    bp_systolic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bp_diastolic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sugar_fasting: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sugar_pp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pulse: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sleep_quality: Mapped[str | None] = mapped_column(String(32), nullable=True)
    food_intake: Mapped[str | None] = mapped_column(String(32), nullable=True)
    water_intake: Mapped[str | None] = mapped_column(String(32), nullable=True)
    energy_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mood: Mapped[str | None] = mapped_column(String(32), nullable=True)

    headache: Mapped[bool] = mapped_column(Boolean, default=False)
    dizziness: Mapped[bool] = mapped_column(Boolean, default=False)
    chest_discomfort: Mapped[bool] = mapped_column(Boolean, default=False)
    breathing_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    body_pain: Mapped[bool] = mapped_column(Boolean, default=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("User", back_populates="health_records")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    alert_level: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_to: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)

    user = relationship("User", back_populates="alerts")


class ApiCost(Base):
    __tablename__ = "api_costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    stt_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    stt_cost_inr: Mapped[float] = mapped_column(Float, default=0.0)
    tts_chars: Mapped[int] = mapped_column(Integer, default=0)
    tts_cost_inr: Mapped[float] = mapped_column(Float, default=0.0)
    llm_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # Split out of llm_tokens so cache behaviour is answerable after the fact.
    # A call where the persona cache worked and one where it silently did not
    # look identical in llm_tokens alone — the prompt is the same size either
    # way, only the price differs.
    llm_cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_cost_inr: Mapped[float] = mapped_column(Float, default=0.0)
    total_cost_inr: Mapped[float] = mapped_column(Float, default=0.0)

    user = relationship("User", back_populates="api_costs")
