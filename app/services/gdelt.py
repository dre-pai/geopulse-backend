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

# Common FIPS 10-4 → ISO 3166-1 alpha-2 mismatches
FIPS_TO_ISO2: dict[str, str] = {
    "UK": "GB",
    "JA": "JP",
    "RQ": "PR",
    "GM": "DE",
    "EN": "EE",
    "LH": "LT",
    "LG": "LV",
    "BO": "BY",
    "BU": "BG",
    "EZ": "CZ",
    "LO": "SK",
    "SP": "ES",
    "PO": "PT",
    "SW": "SE",
    "SZ": "CH",
    "AU": "AT",
    "AS": "AU",
    "VM": "VN",
    "KS": "KR",
    "KN": "KP",
    "CH": "CN",
    "RI": "RS",
    "BK": "BA",
    "MJ": "ME",
    "KV": "XK",
    "TU": "TR",
    "IZ": "IQ",
    "IR": "IR",
    "IS": "IL",
    "AE": "AE",
    "SA": "SA",
    "SF": "ZA",
    "NI": "NG",
    "EG": "EG",
    "IN": "IN",
    "PK": "PK",
    "RS": "RU",
    "UP": "UA",
    "PL": "PL",
    "FR": "FR",
    "IT": "IT",
    "US": "US",
    "CA": "CA",
    "MX": "MX",
    "BR": "BR",
    "AR": "AR",
}


def categorize_cameo(code: str | None) -> EventCategory:
    if not code:
        return EventCategory.OTHER
    root = code[:2]
    return CAMEO_CATEGORY_MAP.get(root, EventCategory.OTHER)


def _safe_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_gdelt_datetime(value: str) -> datetime:
    value = value.strip()
    if len(value) >= 14:
        return datetime.strptime(value[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    if len(value) >= 8:
        return datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _action_geo_fields(row: list[str]) -> tuple[str | None, str | None, float | None, float | None, str | None, str | None]:
    """
    GDELT export gained ADM2 columns, shifting ActionGeo indices.

    Classic (58 cols): Type=49 FullName=50 Country=51 ADM1=52 Lat=53 Long=54 Feature=55 DATE=56 URL=57
    Current (61 cols): Type=51 FullName=52 Country=53 ADM1=54 ADM2=55 Lat=56 Long=57 Feature=58 DATE=59 URL=60
    """
    if len(row) >= 61:
        return (
            row[52] or None,
            (row[53] or "").upper() or None,
            _safe_float(row[56]),
            _safe_float(row[57]),
            row[59] or row[1] or None,
            row[60] or None,
        )
    if len(row) >= 58:
        return (
            row[50] or None,
            (row[51] or "").upper() or None,
            _safe_float(row[53]),
            _safe_float(row[54]),
            row[56] or row[1] or None,
            row[57] or None,
        )
    return None, None, None, None, row[1] if row else None, None


async def resolve_latest_export_url(client: httpx.AsyncClient) -> str:
    response = await client.get(settings.gdelt_last_update_url, timeout=30.0)
    response.raise_for_status()
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
    if len(row) < 35:
        return None

    global_event_id = row[0]
    if not global_event_id:
        return None

    event_code = row[26] if len(row) > 26 else None
    actor1 = row[6] or None if len(row) > 6 else None
    actor2 = row[16] or None if len(row) > 16 else None
    goldstein = _safe_float(row[30]) if len(row) > 30 else None
    avg_tone = _safe_float(row[34]) if len(row) > 34 else None
    sentiment = (avg_tone / 100.0) if avg_tone is not None else None

    location_name, fips, lat, lon, occurred_raw, source_url = _action_geo_fields(row)
    iso_hint = FIPS_TO_ISO2.get(fips, fips) if fips else None
    country = lookup.get(iso_hint) if iso_hint else None

    # Fall back to country centroid when ActionGeo coords are missing
    if (lat is None or lon is None) and country is not None:
        lat = lat if lat is not None else country.latitude
        lon = lon if lon is not None else country.longitude

    occurred_at = (
        _parse_gdelt_datetime(occurred_raw) if occurred_raw else datetime.now(timezone.utc)
    )

    actors = [a for a in [actor1, actor2] if a]
    category = categorize_cameo(event_code)
    title = " / ".join(actors) if actors else f"{category.value.title()} event"
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
        "raw": {"cameo": event_code, "fips": fips, "iso2": iso_hint, "ncols": len(row)},
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
                    try:
                        payload = normalize_event_row(row, lookup)
                    except Exception:  # noqa: BLE001 - skip malformed rows
                        continue
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
