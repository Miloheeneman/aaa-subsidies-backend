# AAA-Subsidies — Backend

FastAPI backend for the AAA-Subsidies platform.

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in .env values
```

## Run (development)

```bash
uvicorn app.main:app --reload --port 8000
```

- API root: `http://localhost:8000/`
- Swagger docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/api/v1/health`

## Database migrations (Alembic)

```bash
alembic revision --autogenerate -m "message"
alembic upgrade head
```

## Deploy (Railway)

- Provision a PostgreSQL plugin, set `DATABASE_URL`.
- Set all variables from `.env.example`.
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
