# Ontomatic

## Installation

```bash
git clone https://github.com/ontomatic/ontomatic.git
cd ontomatic

uv venv .venv
source .venv\Script\activate.bat
uv sync --all-package --locked
```

## Run

From project root directory,

### Run API

```bash
cp packages/backend/.env.example packages/backend/.env # fill environments
uv run --package backend api
```

### Run Streamlit

```bash
uv run --package frontend streamlit run app.py
```

## PostgreSQL with pgvector

Copy `.env.example` to `.env` and set `APP_POSTGRES_PASSWORD`, then run:

```bash
docker compose up -d
docker compose --profile langfuse up -d
```
