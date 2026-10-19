# Ontomatic

## Installation

```bash
git clone ~~.git
cd ~~

uv venv .venv
source .venv\Script\activate.bat
uv sync --locked
```

## Run

From project root directory,

```bash
uv run --package web streamlit run packages/web/app.py # Frontend
uv run --package api api # Backend
```

## PostgreSQL with pgvector

Copy `.env.example` to `.env` and set `APP_POSTGRES_PASSWORD`, then run:

```bash
docker compose up -d app-postgres
docker compose exec app-postgres psql -U ontomatic -d ontomatic -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
```

Local applications connect to `localhost:5432`; containers in the same Compose
project connect to `app-postgres:5432`. Use the database name, user, password,
and port configured in `.env`. The verification command above assumes the default
database name and user.

The database uses PostgreSQL 17 with pgvector and a persistent named volume.
The initialization script enables `vector` when the data volume is first created.
For an existing database, run `CREATE EXTENSION IF NOT EXISTS vector;` manually.
`docker compose down` retains data; `docker compose down -v` deletes it.

This database is for the application; Langfuse can keep its own database service.
