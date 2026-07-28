import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Country, Event
from app.services.countries import seed_countries_from_restcountries
from app.services.gdelt import fetch_and_ingest_gdelt
from app.services.risk import compute_country_risk
from app.workers.celery_app import celery_app


def _run(coro):
    return asyncio.run(coro)


@celery_app.task(name="app.workers.tasks.ingest_gdelt_task")
def ingest_gdelt_task(limit: int = 5000) -> dict:
    db = SessionLocal()
    try:
        _run(seed_countries_from_restcountries(db))
        run = _run(fetch_and_ingest_gdelt(db, limit=limit))
        return {
            "status": run.status,
            "fetched": run.records_fetched,
            "upserted": run.records_upserted,
            "run_id": run.id,
        }
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.recompute_hot_risk_scores")
def recompute_hot_risk_scores(limit: int = 25) -> dict:
    db = SessionLocal()
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        rows = db.execute(
            select(Country.id, func.count(Event.id))
            .join(Event, Event.country_id == Country.id)
            .where(Event.occurred_at >= since)
            .group_by(Country.id)
            .order_by(func.count(Event.id).desc())
            .limit(limit)
        ).all()
        computed = []
        for country_id, _count in rows:
            risk = compute_country_risk(db, country_id)
            computed.append({"country_id": country_id, "score": risk.score, "level": risk.level})
        return {"computed": computed}
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.seed_countries_task")
def seed_countries_task() -> dict:
    db = SessionLocal()
    try:
        created = _run(seed_countries_from_restcountries(db))
        return {"created": created}
    finally:
        db.close()
