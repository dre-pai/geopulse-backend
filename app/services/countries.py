from __future__ import annotations

from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Country

settings = get_settings()


def _flag_url(iso2: str, flags: dict | None = None) -> str | None:
    if flags:
        if isinstance(flags, dict):
            svg = flags.get("svg") or flags.get("png")
            if isinstance(svg, str):
                return svg
    return f"https://flagcdn.com/{iso2.lower()}.svg"


async def seed_countries_from_restcountries(db: Session) -> int:
    """Seed country metadata from the public mledoze/countries dataset."""
    existing = db.scalar(select(Country.id).limit(1))
    if existing is not None:
        return 0

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(settings.countries_dataset_url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Unexpected countries dataset payload shape")

    created = 0
    for item in payload:
        name = item.get("name", {}).get("common")
        iso2 = item.get("cca2")
        iso3 = item.get("cca3")
        if not name or not iso2 or not iso3:
            continue
        latlng = item.get("latlng") or [None, None]
        capital_list = item.get("capital") or []
        country = Country(
            iso2=iso2.upper(),
            iso3=iso3.upper(),
            name=name,
            capital=capital_list[0] if capital_list else None,
            region=item.get("region"),
            subregion=item.get("subregion"),
            latitude=latlng[0] if len(latlng) > 0 else None,
            longitude=latlng[1] if len(latlng) > 1 else None,
            population=item.get("population"),
            flag_url=_flag_url(iso2, item.get("flags")),
            borders=item.get("borders") or [],
            currencies=item.get("currencies") or {},
            languages=item.get("languages") or {},
        )
        db.add(country)
        created += 1

    db.commit()
    return created


async def fetch_world_bank_indicator(
    iso2: str,
    indicator: str = "NY.GDP.MKTP.CD",
    per_page: int = 5,
) -> Optional[list[dict]]:
    url = (
        f"{settings.world_bank_base_url}/country/{iso2}/indicator/{indicator}"
        f"?format=json&per_page={per_page}"
    )
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, list) or len(data) < 2:
        return None
    return data[1]
