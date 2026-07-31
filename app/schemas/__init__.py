from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CountryBase(BaseModel):
    iso2: str
    iso3: str
    name: str
    capital: Optional[str] = None
    region: Optional[str] = None
    subregion: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    population: Optional[int] = None
    flag_url: Optional[str] = None


class CountryOut(CountryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    borders: Optional[list] = None
    currencies: Optional[dict] = None
    languages: Optional[dict] = None


class CountryDetail(CountryOut):
    risk_score: Optional[float] = None
    risk_level: Optional[str] = None
    events_today: int = 0


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    source: str
    title: str
    summary: Optional[str] = None
    category: str
    event_type: Optional[str] = None
    actors: Optional[list] = None
    sentiment: Optional[float] = None
    goldstein_scale: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_name: Optional[str] = None
    source_url: Optional[str] = None
    occurred_at: datetime
    country_id: Optional[int] = None
    country_name: Optional[str] = None
    country_iso2: Optional[str] = None


class RiskScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    country_id: int
    score: float
    level: str
    conflict_component: float
    economic_component: float
    diplomatic_component: float
    media_sentiment_component: float
    details: Optional[dict] = None
    computed_at: datetime


class TimelinePoint(BaseModel):
    date: datetime
    category: str
    title: str
    event_id: int
    sentiment: Optional[float] = None


class SearchResult(BaseModel):
    query: str
    total: int
    events: list[EventOut]
    countries: list[CountryOut] = Field(default_factory=list)


class StatsOut(BaseModel):
    total_events: int
    total_countries: int
    events_last_24h: int
    top_categories: list[dict]
    hottest_countries: list[dict]


class SummaryRequest(BaseModel):
    country_id: Optional[int] = None
    iso2: Optional[str] = None
    days: int = 30


class SummaryOut(BaseModel):
    country: str
    days: int
    summary: str
    event_count: int
    generated_at: datetime
    model: Optional[str] = None


class RelationshipNode(BaseModel):
    id: str
    label: str
    iso2: Optional[str] = None


class RelationshipLink(BaseModel):
    source: str
    target: str
    relationship_type: str
    strength: float = 1.0


class RelationshipGraph(BaseModel):
    nodes: list[RelationshipNode]
    links: list[RelationshipLink]
