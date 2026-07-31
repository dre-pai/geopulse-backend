from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Country, Event, RelationshipEdge, RiskScore
from app.schemas import (
    CountryDetail,
    CountryOut,
    EventOut,
    RelationshipGraph,
    RelationshipLink,
    RelationshipNode,
    RiskScoreOut,
    SearchResult,
    StatsOut,
    SummaryOut,
    SummaryRequest,
    TimelinePoint,
)
from app.services.countries import fetch_world_bank_indicator
from app.services.risk import compute_country_risk, events_today_count, get_country_by_iso, latest_risk
from app.services.summarizer import generate_country_summary

router = APIRouter()


def serialize_event(event: Event) -> EventOut:
    payload = EventOut.model_validate(event)
    if event.country is None:
        return payload
    return payload.model_copy(
        update={
            "country_name": event.country.name,
            "country_iso2": event.country.iso2,
        }
    )


def events_query() -> Select[tuple[Event]]:
    return select(Event).options(joinedload(Event.country))


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/countries", response_model=list[CountryOut])
def list_countries(
    q: Optional[str] = None,
    region: Optional[str] = None,
    limit: int = Query(250, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[Country]:
    stmt: Select[tuple[Country]] = select(Country).order_by(Country.name).limit(limit)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(Country.name.ilike(pattern), Country.iso2.ilike(pattern)))
    if region:
        stmt = stmt.where(Country.region == region)
    return list(db.scalars(stmt))


@router.get("/countries/{country_ref}", response_model=CountryDetail)
def get_country(country_ref: str, db: Session = Depends(get_db)) -> CountryDetail:
    country: Country | None
    if country_ref.isdigit():
        country = db.get(Country, int(country_ref))
    else:
        country = get_country_by_iso(db, country_ref)

    if country is None:
        raise HTTPException(status_code=404, detail="Country not found")

    risk = latest_risk(db, country.id)
    return CountryDetail(
        id=country.id,
        iso2=country.iso2,
        iso3=country.iso3,
        name=country.name,
        capital=country.capital,
        region=country.region,
        subregion=country.subregion,
        latitude=country.latitude,
        longitude=country.longitude,
        population=country.population,
        flag_url=country.flag_url,
        borders=country.borders,
        currencies=country.currencies,
        languages=country.languages,
        risk_score=risk.score if risk else None,
        risk_level=risk.level if risk else None,
        events_today=events_today_count(db, country.id),
    )


@router.get("/countries/{country_ref}/indicators")
async def country_indicators(country_ref: str, db: Session = Depends(get_db)) -> dict:
    country = (
        db.get(Country, int(country_ref))
        if country_ref.isdigit()
        else get_country_by_iso(db, country_ref)
    )
    if country is None:
        raise HTTPException(status_code=404, detail="Country not found")
    gdp = await fetch_world_bank_indicator(country.iso2, "NY.GDP.MKTP.CD")
    inflation = await fetch_world_bank_indicator(country.iso2, "FP.CPI.TOTL.ZG")
    return {"iso2": country.iso2, "gdp": gdp, "inflation": inflation}


@router.get("/events", response_model=list[EventOut])
def list_events(
    country: Optional[str] = None,
    type: Optional[str] = Query(None, alias="type"),
    category: Optional[str] = None,
    q: Optional[str] = None,
    hours: Optional[int] = Query(None, ge=1, le=168),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[EventOut]:
    stmt: Select[tuple[Event]] = events_query().order_by(Event.occurred_at.desc()).limit(limit)
    if hours is not None:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        stmt = stmt.where(Event.occurred_at >= since)
    if country:
        c = get_country_by_iso(db, country)
        if c is None:
            raise HTTPException(status_code=404, detail="Country not found")
        stmt = stmt.where(Event.country_id == c.id)
    cat = category or type
    if cat:
        stmt = stmt.where(Event.category == cat.lower())
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(Event.title.ilike(pattern), Event.location_name.ilike(pattern)))
    return [serialize_event(event) for event in db.scalars(stmt).unique()]


@router.get("/events/trending", response_model=list[EventOut])
def trending_events(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)) -> list[EventOut]:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    stmt = (
        events_query()
        .where(Event.occurred_at >= since)
        .order_by(Event.goldstein_scale.asc().nullslast(), Event.occurred_at.desc())
        .limit(limit)
    )
    return [serialize_event(event) for event in db.scalars(stmt).unique()]


@router.get("/risk", response_model=list[RiskScoreOut])
def list_risk(limit: int = Query(50, ge=1, le=250), db: Session = Depends(get_db)) -> list[RiskScore]:
    # Latest risk per country via distinct on country_id
    subquery = (
        select(RiskScore.country_id, func.max(RiskScore.computed_at).label("max_computed"))
        .group_by(RiskScore.country_id)
        .subquery()
    )
    stmt = (
        select(RiskScore)
        .join(
            subquery,
            (RiskScore.country_id == subquery.c.country_id)
            & (RiskScore.computed_at == subquery.c.max_computed),
        )
        .order_by(RiskScore.score.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


@router.post("/risk/{country_ref}/recompute", response_model=RiskScoreOut)
def recompute_risk(country_ref: str, days: int = 30, db: Session = Depends(get_db)) -> RiskScore:
    country = (
        db.get(Country, int(country_ref))
        if country_ref.isdigit()
        else get_country_by_iso(db, country_ref)
    )
    if country is None:
        raise HTTPException(status_code=404, detail="Country not found")
    return compute_country_risk(db, country.id, days=days)


@router.get("/timeline", response_model=list[TimelinePoint])
def timeline(
    country: Optional[str] = None,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[TimelinePoint]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = select(Event).where(Event.occurred_at >= since).order_by(Event.occurred_at.desc()).limit(limit)
    if country:
        c = get_country_by_iso(db, country)
        if c is None:
            raise HTTPException(status_code=404, detail="Country not found")
        stmt = stmt.where(Event.country_id == c.id)
    events = list(db.scalars(stmt))
    return [
        TimelinePoint(
            date=e.occurred_at,
            category=e.category,
            title=e.title,
            event_id=e.id,
            sentiment=e.sentiment,
        )
        for e in events
    ]


@router.get("/search", response_model=SearchResult)
def search(q: str = Query(..., min_length=2), limit: int = 50, db: Session = Depends(get_db)) -> SearchResult:
    pattern = f"%{q}%"
    events = [
        serialize_event(event)
        for event in db.scalars(
            events_query()
            .where(or_(Event.title.ilike(pattern), Event.location_name.ilike(pattern)))
            .order_by(Event.occurred_at.desc())
            .limit(limit)
        ).unique()
    ]
    countries = list(
        db.scalars(
            select(Country)
            .where(or_(Country.name.ilike(pattern), Country.iso2.ilike(pattern)))
            .limit(20)
        )
    )
    return SearchResult(query=q, total=len(events), events=events, countries=countries)


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db)) -> StatsOut:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    total_events = int(db.scalar(select(func.count()).select_from(Event)) or 0)
    total_countries = int(db.scalar(select(func.count()).select_from(Country)) or 0)
    events_last_24h = int(
        db.scalar(select(func.count()).select_from(Event).where(Event.occurred_at >= since)) or 0
    )
    top_categories = [
        {"category": row[0], "count": row[1]}
        for row in db.execute(
            select(Event.category, func.count())
            .where(Event.occurred_at >= since)
            .group_by(Event.category)
            .order_by(func.count().desc())
            .limit(8)
        )
    ]
    hottest = [
        {"country_id": row[0], "name": row[1], "count": row[2]}
        for row in db.execute(
            select(Country.id, Country.name, func.count(Event.id))
            .join(Event, Event.country_id == Country.id)
            .where(Event.occurred_at >= since)
            .group_by(Country.id, Country.name)
            .order_by(func.count(Event.id).desc())
            .limit(10)
        )
    ]
    return StatsOut(
        total_events=total_events,
        total_countries=total_countries,
        events_last_24h=events_last_24h,
        top_categories=top_categories,
        hottest_countries=hottest,
    )


@router.get("/relationships/{country_ref}", response_model=RelationshipGraph)
def relationships(country_ref: str, db: Session = Depends(get_db)) -> RelationshipGraph:
    country = (
        db.get(Country, int(country_ref))
        if country_ref.isdigit()
        else get_country_by_iso(db, country_ref)
    )
    if country is None:
        raise HTTPException(status_code=404, detail="Country not found")

    edges = list(
        db.scalars(
            select(RelationshipEdge).where(
                or_(
                    RelationshipEdge.source_country_id == country.id,
                    RelationshipEdge.target_country_id == country.id,
                )
            )
        )
    )
    country_ids = {country.id}
    for edge in edges:
        country_ids.add(edge.source_country_id)
        country_ids.add(edge.target_country_id)

    countries = {
        c.id: c for c in db.scalars(select(Country).where(Country.id.in_(country_ids))).all()
    }
    nodes = [
        RelationshipNode(id=str(c.id), label=c.name, iso2=c.iso2) for c in countries.values()
    ]
    links = [
        RelationshipLink(
            source=str(e.source_country_id),
            target=str(e.target_country_id),
            relationship_type=e.relationship_type,
            strength=e.strength,
        )
        for e in edges
    ]

    # Fallback demo graph when no edges ingested yet
    if not links and country.borders:
        for iso3 in country.borders[:8]:
            neighbor = db.scalar(select(Country).where(Country.iso3 == iso3))
            if neighbor is None:
                continue
            nodes.append(
                RelationshipNode(id=str(neighbor.id), label=neighbor.name, iso2=neighbor.iso2)
            )
            links.append(
                RelationshipLink(
                    source=str(country.id),
                    target=str(neighbor.id),
                    relationship_type="border",
                    strength=0.5,
                )
            )
        # de-dupe nodes
        uniq = {n.id: n for n in nodes}
        nodes = list(uniq.values())

    return RelationshipGraph(nodes=nodes, links=links)


@router.post("/summarize", response_model=SummaryOut)
async def summarize(body: SummaryRequest, db: Session = Depends(get_db)) -> SummaryOut:
    try:
        return await generate_country_summary(
            db, country_id=body.country_id, iso2=body.iso2, days=body.days
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
