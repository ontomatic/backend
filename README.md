# Ontomatic

## Installation

```bash
git clone ~~.git
cd ~~

uv venv .venv
source .venv\Script\activate.bat
uv sync --all-package --locked
```

## Run

From project root directory,

### Run API

```bash
cp packages/backend/.env.example packages/backend/.env
uv run --package backend api # Backend
```

## PostgreSQL with pgvector

Copy `.env.example` to `.env` and set `APP_POSTGRES_PASSWORD`, then run:

```bash
docker compose up -d
docker compose --profile langfuse up -d
```
