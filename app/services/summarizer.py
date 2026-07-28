from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Country, Event
from app.schemas import SummaryOut
from app.services.risk import get_country_by_iso

settings = get_settings()


def _heuristic_summary(country: Country, events: list[Event], days: int) -> str:
    if not events:
        return (
            f"{country.name} showed limited indexed geopolitical activity over the last {days} days. "
            "Continue monitoring diplomatic, economic, and security channels."
        )

    by_category: dict[str, int] = {}
    for event in events:
        by_category[event.category] = by_category.get(event.category, 0) + 1

    top = sorted(by_category.items(), key=lambda item: item[1], reverse=True)[:3]
    top_text = ", ".join(f"{count} {category}" for category, count in top)
    sentiments = [e.sentiment for e in events if e.sentiment is not None]
    tone = "mixed"
    if sentiments:
        avg = sum(sentiments) / len(sentiments)
        if avg > 0.15:
            tone = "constructive"
        elif avg < -0.15:
            tone = "tense"

    return (
        f"{country.name} registered {len(events)} tracked events over the last {days} days, "
        f"led by {top_text}. Overall media tone appears {tone}. "
        "Priority watch items include security signaling, sanctions/economic pressure, and diplomatic coordination."
    )


async def generate_country_summary(
    db: Session,
    *,
    country_id: int | None = None,
    iso2: str | None = None,
    days: int = 30,
) -> SummaryOut:
    country: Country | None = None
    if country_id is not None:
        country = db.get(Country, country_id)
    elif iso2:
        country = get_country_by_iso(db, iso2)

    if country is None:
        raise ValueError("Country not found")

    since = datetime.now(timezone.utc) - timedelta(days=days)
    events = list(
        db.scalars(
            select(Event)
            .where(Event.country_id == country.id, Event.occurred_at >= since)
            .order_by(Event.occurred_at.desc())
            .limit(200)
        )
    )

    model_name: str | None = None
    summary: str

    if settings.ai_summary_enabled and settings.openai_api_key:
        model_name = settings.openai_model
        bullet_lines = [
            f"- [{e.occurred_at.date()}] {e.category}: {e.title}" for e in events[:80]
        ]
        prompt = (
            f"Write a concise geopolitical situation report for {country.name} "
            f"covering the last {days} days. Use only the events below.\n\n"
            + "\n".join(bullet_lines)
        )
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    json={
                        "model": settings.openai_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a geopolitical analyst. Be precise and neutral.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.3,
                    },
                )
                response.raise_for_status()
                summary = response.json()["choices"][0]["message"]["content"].strip()
        except Exception:  # noqa: BLE001 - fall back to deterministic summary
            summary = _heuristic_summary(country, events, days)
            model_name = "heuristic-fallback"
    else:
        summary = _heuristic_summary(country, events, days)
        model_name = "heuristic"

    return SummaryOut(
        country=country.name,
        days=days,
        summary=summary,
        event_count=len(events),
        generated_at=datetime.now(timezone.utc),
        model=model_name,
    )
