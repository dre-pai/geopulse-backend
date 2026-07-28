from datetime import datetime, timezone

from app.services.risk import risk_level
from app.services.gdelt import categorize_cameo
from app.models import EventCategory


def test_risk_level_thresholds():
    assert risk_level(10) == "LOW"
    assert risk_level(40) == "ELEVATED"
    assert risk_level(60) == "HIGH"
    assert risk_level(90) == "CRITICAL"


def test_cameo_categorization():
    assert categorize_cameo("145") == EventCategory.MILITARY
    assert categorize_cameo("051") == EventCategory.DIPLOMACY
    assert categorize_cameo(None) == EventCategory.OTHER


def test_event_category_values_stable():
    assert EventCategory.SANCTIONS.value == "sanctions"
    assert datetime.now(timezone.utc).tzinfo is not None
