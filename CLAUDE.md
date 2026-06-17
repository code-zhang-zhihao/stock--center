# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`stock-center` is a market data and data engine backend, upgraded from the older `stock-analysis` project. Design principle: **database is the first-class asset; providers are the fill-in and refresh mechanism.** All external responses are raw-landed first, then optionally written to canonical tables.

**Reference project** (read-only, do NOT implement here):
- `/Volumes/TiPro9000/projects/archived/stock-analysis`

## Project Structure

```
stock-center/
  python-back/              # FastAPI Python backend
  web-admin/                # Vue3 configuration admin frontend
  docs/                     # SQL scripts, capability matrix, migration docs
  stock-center-wiki/        # Project wiki and AI collaboration rules
  start.sh                  # Main launcher script (backend + frontend)
```

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), asyncpg, APScheduler, akshare, mootdx
- **Frontend**: Vue 3, TypeScript, Vite, Naive UI, vue-router
- **Database**: PostgreSQL (all new tables use `t_` prefix)

## Commands

### Quick Start

```bash
# Install deps and start both backend + frontend
./start.sh --install

# Start both (after deps installed)
./start.sh

# Backend only
./start.sh --backend-only

# Show help
./start.sh --help
```

### Backend Development

```bash
# Install backend deps manually
pip install -e python-back/

# Run backend with hot reload
cd python-back && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Run tests
cd python-back && pytest
```

### Frontend Development

```bash
cd web-admin

# Install deps
npm install

# Dev server (127.0.0.1:8080)
npm run dev

# Type check
npm run typecheck

# Production build
npm run build
```

### API Access

- Backend: `http://127.0.0.1:8000`
- Swagger UI: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/api/v1/health`
- Frontend: `http://127.0.0.1:8080`

## Architecture

### Layered Architecture

```
API Routes → Query/Sync Services → Capability Registry → Providers → Repositories → DB
                                                          ↑
                                                    AkShare / MooTDX
```

### Backend Module Pattern

Each module follows: `api.py` (router) → `service.py` (business logic) → `repository.py` (DB) → `models.py` (ORM) → `schemas.py` (Pydantic)

Key modules:
- **market_data** — `MarketDataQueryService` (5 query modes), `MarketDataSyncService`, provider chain, capability registry
- **config_center** — ConfigCenterService (Search, LLM, Notification, Key pools)
- **scheduler_center** — APScheduler-based job management
- **llm_runtime** — Internal OpenAI-compatible model calls
- **skill_runtime** — Project-internal Skill execution

### Query Modes

All market data queries go through `MarketDataQueryService`:
- `db_first` — Query DB first, fill from provider chain if missing/stale
- `provider_first` — Query external source first, write to DB on success
- `db_only` — DB only
- `provider_only` — External source only, no canonical write (raw landing preserved)
- `refresh` — Force refresh and upsert canonical table

### Database Schema

- **Raw**: `t_provider_raw_record` — stores raw provider responses
- **Canonical**: `t_stock`, `t_daily_bar`, `t_minute_bar`, `t_quote_snapshot`, `t_sector_basic`, `t_sector_component`, etc.
- **Derived**: `t_stock_factor_daily`, `t_stock_factor_minute`, `t_technical_indicator_snapshot`
- **Config**: `t_system_config`, `t_config_value`, `t_config_option`
- **Scheduler**: `t_scheduler_job`, `t_scheduler_job_run`
- **Runtime**: `t_runtime_call_log`

Schema SQL is in `docs/sql/01-schema.sql`. Migration from old tables: `docs/sql/02-stock-analysis-migration-mapping.sql`.

### API Routes

- `/api/v1/market-data/query/*` — Market data queries (daily-bars, minute-bars, quote, sectors, etc.)
- `/api/v1/config/*` — Configuration management
- `/api/v1/scheduler/*` — Job scheduling (jobs, runs, status)
- `/api/v1/health` — Health check

## Important Notes

- **`DATABASE_URL`** in `python-back/.env` should point to the existing `stock-analysis` database
- **`CONFIG_MASTER_KEY`** must be set in `.env` (do not commit to repo)
- New `t_` tables must be created manually via `docs/sql/01-schema.sql` before first run
- Config center v2 requires `docs/sql/08-config-center-v2-rebuild.sql` before starting
- The `start.sh` script does NOT initialize database tables — run SQL scripts manually first
- All new code goes in this `stock-center` repo, never in the `stock-analysis` reference project

## AI Collaboration Rules

See `stock-center-wiki/60-AI协作规范/AI协作规则.md` — requires reading the wiki before making changes, and syncing the wiki after changes that alter project behavior.
