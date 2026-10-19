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
