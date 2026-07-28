from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import Country, Event, EventCategory, RiskScore


WEIGHTS = {
    "conflict": 0.40,
    "economic": 0.25,
    "diplomatic": 0.20,
    "media_sentiment": 0.15,
}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def risk_level(score: float) -> str:
    if score >= 75:
        return "CRITICAL"
    if score >= 55:
        return "HIGH"
    if score >= 35:
        return "ELEVATED"
    if score >= 20:
        return "MODERATE"
    return "LOW"


def compute_country_risk(db: Session, country_id: int, days: int = 30) -> RiskScore:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    events = list(
        db.scalars(
            select(Event).where(Event.country_id == country_id, Event.occurred_at >= since)
        )
    )

    military = sum(1 for e in events if e.category == EventCategory.MILITARY)
    terrorism = sum(1 for e in events if e.category == EventCategory.TERRORISM)
    sanctions = sum(1 for e in events if e.category == EventCategory.SANCTIONS)
    economics = sum(1 for e in events if e.category == EventCategory.ECONOMICS)
    diplomacy = sum(1 for e in events if e.category == EventCategory.DIPLOMACY)
    elections = sum(1 for e in events if e.category == EventCategory.ELECTIONS)

    sentiments = [e.sentiment for e in events if e.sentiment is not None]
    avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.0

    conflict = _clamp((military * 8.0) + (terrorism * 12.0) + (sanctions * 5.0))
    economic = _clamp(economics * 4.0 + abs(min(avg_sentiment, 0)) * 20.0)
    diplomatic = _clamp(diplomacy * 3.5 + elections * 2.5)
    media = _clamp(50.0 - (avg_sentiment * 50.0))

    score = _clamp(
        conflict * WEIGHTS["conflict"]
        + economic * WEIGHTS["economic"]
        + diplomatic * WEIGHTS["diplomatic"]
        + media * WEIGHTS["media_sentiment"]
    )

    risk = RiskScore(
        country_id=country_id,
        score=round(score, 1),
        level=risk_level(score),
        conflict_component=round(conflict, 1),
        economic_component=round(economic, 1),
        diplomatic_component=round(diplomatic, 1),
        media_sentiment_component=round(media, 1),
        details={
            "window_days": days,
            "event_count": len(events),
            "weights": WEIGHTS,
            "counts": {
                "military": military,
                "terrorism": terrorism,
                "sanctions": sanctions,
                "economics": economics,
                "diplomacy": diplomacy,
                "elections": elections,
            },
            "avg_sentiment": round(avg_sentiment, 3),
        },
    )
    db.add(risk)
    db.commit()
    db.refresh(risk)
    return risk


def latest_risk(db: Session, country_id: int) -> Optional[RiskScore]:
    stmt: Select[tuple[RiskScore]] = (
        select(RiskScore)
        .where(RiskScore.country_id == country_id)
        .order_by(RiskScore.computed_at.desc())
        .limit(1)
    )
    return db.scalar(stmt)


def events_today_count(db: Session, country_id: int) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.scalar(
            select(func.count())
            .select_from(Event)
            .where(Event.country_id == country_id, Event.occurred_at >= start)
        )
        or 0
    )


def get_country_by_iso(db: Session, iso: str) -> Optional[Country]:
    value = iso.upper()
    if len(value) == 2:
        return db.scalar(select(Country).where(Country.iso2 == value))
    return db.scalar(select(Country).where(Country.iso3 == value))
