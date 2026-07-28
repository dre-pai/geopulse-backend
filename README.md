# GeoPulse Backend

Real-time geopolitical intelligence API for the GeoPulse dashboard.

## Stack

- **FastAPI** + **SQLAlchemy** + **Postgres**
- **Celery** workers with **RabbitMQ** broker (no Redis)
- Celery results stored in **Postgres**
- GDELT ingestion, REST Countries seed, World Bank indicators
- Heuristic + optional OpenAI situation summaries
- Docker Compose + GitHub Actions CI

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

API: http://localhost:8000  
Docs: http://localhost:8000/docs  
RabbitMQ UI: http://localhost:15672 (`geopulse` / `geopulse`)

### Local (without Docker for the API process)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Trigger a one-off GDELT ingest:

```bash
celery -A app.workers.celery_app.celery_app call app.workers.tasks.ingest_gdelt_task
```

## API surface

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/countries` | List countries |
| GET | `/api/v1/countries/{id\|iso}` | Country detail + risk |
| GET | `/api/v1/events` | Filterable events |
| GET | `/api/v1/events/trending` | Hot events (24h) |
| GET | `/api/v1/risk` | Latest risk scores |
| POST | `/api/v1/risk/{id}/recompute` | Recompute risk |
| GET | `/api/v1/timeline` | Timeline points |
| GET | `/api/v1/search?q=` | Search events/countries |
| GET | `/api/v1/stats` | Aggregate stats |
| GET | `/api/v1/relationships/{id}` | Alliance/border graph |
| POST | `/api/v1/summarize` | AI / heuristic briefing |

## Risk score

Weighted composite (interview-friendly derived metric):

- 40% conflict (military / terrorism / sanctions volume)
- 25% economic
- 20% diplomatic
- 15% media sentiment

## Architecture

```
Celery Beat → GDELT fetch → normalize → Postgres
                 ↓
            Celery worker → risk recompute
                 ↓
            FastAPI REST → React Query (frontend)
```

Companion frontend: `../geopulse-frontend`
