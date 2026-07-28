from datetime import datetime
from enum import StrEnum
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EventCategory(StrEnum):
    MILITARY = "military"
    ECONOMICS = "economics"
    DIPLOMACY = "diplomacy"
    SANCTIONS = "sanctions"
    ELECTIONS = "elections"
    ENVIRONMENT = "environment"
    TERRORISM = "terrorism"
    OTHER = "other"


class Country(Base):
    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    iso2: Mapped[str] = mapped_column(String(2), unique=True, index=True)
    iso3: Mapped[str] = mapped_column(String(3), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    capital: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    subregion: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    population: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    flag_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    borders: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    currencies: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    languages: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    events: Mapped[list["Event"]] = relationship(back_populates="country")
    risk_scores: Mapped[list["RiskScore"]] = relationship(back_populates="country")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_country_occurred", "country_id", "occurred_at"),
        Index("ix_events_category_occurred", "category", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(32), default="gdelt", index=True)
    title: Mapped[str] = mapped_column(String(512))
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    actors: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    sentiment: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    goldstein_scale: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    location_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    country_id: Mapped[Optional[int]] = mapped_column(ForeignKey("countries.id"), nullable=True)
    raw: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    country: Mapped[Optional[Country]] = relationship(back_populates="events")


class RiskScore(Base):
    __tablename__ = "risk_scores"
    __table_args__ = (Index("ix_risk_country_computed", "country_id", "computed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    level: Mapped[str] = mapped_column(String(16))
    conflict_component: Mapped[float] = mapped_column(Float, default=0.0)
    economic_component: Mapped[float] = mapped_column(Float, default=0.0)
    diplomatic_component: Mapped[float] = mapped_column(Float, default=0.0)
    media_sentiment_component: Mapped[float] = mapped_column(Float, default=0.0)
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    country: Mapped[Country] = relationship(back_populates="risk_scores")


class RelationshipEdge(Base):
    __tablename__ = "relationship_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_country_id: Mapped[int] = mapped_column(ForeignKey("countries.id"), index=True)
    target_country_id: Mapped[int] = mapped_column(ForeignKey("countries.id"), index=True)
    relationship_type: Mapped[str] = mapped_column(String(64), index=True)
    strength: Mapped[float] = mapped_column(Float, default=1.0)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    records_fetched: Mapped[int] = mapped_column(Integer, default=0)
    records_upserted: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
