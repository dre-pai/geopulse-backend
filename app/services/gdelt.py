from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timezone
from typing import Optional
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Country, Event, EventCategory, IngestionRun

settings = get_settings()

# Cameo event root codes → GeoPulse categories (simplified mapping)
CAMEO_CATEGORY_MAP: dict[str, EventCategory] = {
    "01": EventCategory.DIPLOMACY,
    "02": EventCategory.DIPLOMACY,
    "03": EventCategory.DIPLOMACY,
    "04": EventCategory.DIPLOMACY,
    "05": EventCategory.DIPLOMACY,
    "06": EventCategory.ECONOMICS,
    "07": EventCategory.ECONOMICS,
    "08": EventCategory.ECONOMICS,
    "09": EventCategory.SANCTIONS,
    "10": EventCategory.SANCTIONS,
    "11": EventCategory.DIPLOMACY,
    "12": EventCategory.MILITARY,
    "13": EventCategory.MILITARY,
    "14": EventCategory.MILITARY,
    "15": EventCategory.MILITARY,
    "16": EventCategory.MILITARY,
    "17": EventCategory.MILITARY,
    "18": EventCategory.TERRORISM,
    "19": EventCategory.MILITARY,
    "20": EventCategory.MILITARY,
}


def categorize_cameo(code: str | None) -> EventCategory:
    if not code:
        return EventCategory.OTHER
    root = code[:2]
    return CAMEO_CATEGORY_MAP.get(root, EventCategory.OTHER)


def _parse_gdelt_timestamp(value: str) -> datetime:
    # GDELT uses YYYYMMDDHHMMSS
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


async def resolve_latest_export_url(client: httpx.AsyncClient) -> str:
    response = await client.get(settings.gdelt_last_update_url, timeout=30.0)
    response.raise_for_status()
    # Format: <bytes> <hash> <url>
    first_line = response.text.strip().splitlines()[0]
    parts = first_line.split()
    if len(parts) < 3:
        raise RuntimeError(f"Unexpected GDELT lastupdate payload: {first_line}")
    return parts[2]


def _country_lookup(db: Session) -> dict[str, Country]:
    countries = db.scalars(select(Country)).all()
    by_iso3 = {c.iso3.upper(): c for c in countries}
    by_iso2 = {c.iso2.upper(): c for c in countries}
    by_name = {c.name.upper(): c for c in countries}
    return {**by_iso3, **by_iso2, **by_name}


def normalize_event_row(row: list[str], lookup: dict[str, Country]) -> Optional[dict]:
    """Normalize a GDELT 2.0 Events TSV row into our Event shape."""
    if len(row) < 58:
        return None

    global_event_id = row[0]
    event_code = row[26]
    actor1 = row[6] or None
    actor2 = row[16] or None
    goldstein = float(row[30]) if row[30] else None
    avg_tone = float(row[34]) if row[34] else None
    # AvgTone is roughly -100..100; normalize to -1..1
    sentiment = (avg_tone / 100.0) if avg_tone is not None else None
    action_geo_country = (row[51] or row[37] or "").upper() or None
    lat = float(row[53]) if row[53] else (float(row[39]) if row[39] else None)
    lon = float(row[54]) if row[54] else (float(row[40]) if row[40] else None)
    location_name = row[50] or row[36] or None
    source_url = row[60] if len(row) > 60 else None
    occurred_at = _parse_gdelt_timestamp(row[1]) if row[1] else datetime.now(timezone.utc)

    country = None
    if action_geo_country:
        country = lookup.get(action_geo_country)

    actors = [a for a in [actor1, actor2] if a]
    title_bits = [a for a in actors if a]
    category = categorize_cameo(event_code)
    title = " / ".join(title_bits) if title_bits else f"{category.value.title()} event"
    if location_name:
        title = f"{title} — {location_name}"

    return {
        "external_id": f"gdelt:{global_event_id}",
        "source": "gdelt",
        "title": title[:512],
        "summary": None,
        "category": category.value,
        "event_type": event_code,
        "actors": actors,
        "sentiment": sentiment,
        "goldstein_scale": goldstein,
        "latitude": lat,
        "longitude": lon,
        "location_name": location_name,
        "source_url": source_url,
        "occurred_at": occurred_at,
        "country_id": country.id if country else None,
        "raw": {"cameo": event_code, "country_code": action_geo_country},
    }


async def fetch_and_ingest_gdelt(db: Session, limit: int = 5000) -> IngestionRun:
    run = IngestionRun(source="gdelt", status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    lookup = _country_lookup(db)
    upserted = 0
    fetched = 0

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            export_url = await resolve_latest_export_url(client)
            zip_response = await client.get(export_url, timeout=120.0)
            zip_response.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(zip_response.content)) as zf:
            names = zf.namelist()
            if not names:
                raise RuntimeError("GDELT export zip was empty")
            with zf.open(names[0]) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
                reader = csv.reader(text, delimiter="\t")
                for row in reader:
                    fetched += 1
                    payload = normalize_event_row(row, lookup)
                    if not payload:
                        continue

                    existing = db.scalar(
                        select(Event).where(Event.external_id == payload["external_id"])
                    )
                    if existing:
                        for key, value in payload.items():
                            setattr(existing, key, value)
                    else:
                        db.add(Event(**payload))
                    upserted += 1
                    if upserted >= limit:
                        break
                    if upserted % 200 == 0:
                        db.commit()

        run.status = "succeeded"
        run.records_fetched = fetched
        run.records_upserted = upserted
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        return run
    except Exception as exc:  # noqa: BLE001 - persist failure on the run record
        run.status = "failed"
        run.records_fetched = fetched
        run.records_upserted = upserted
        run.error_message = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise
