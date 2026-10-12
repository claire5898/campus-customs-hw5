# Campus Customs Multi-Agent Operations (HW5)

A local MCP server, FastAPI backend with a PydanticAI agent team, and React/Vite dashboard for investigating Campus Customs tickets. The app uses SQLite as its source of truth. Agents can investigate and recommend; ticket resolution and financial actions require an explicit human action in the dashboard.

## Project layout

- `data/campus_customs.db` — untouched reset source.
- `data/campus_customs_new.db` — working database used by the MCP server and backend; it currently contains the completed Problem 9 ticket run.
- `mcp_server/` — FastMCP tools backed by the working database.
- `backend/` — FastAPI routes, agent team, prompts, and backend requirements.
- `frontend/` — React + Vite + TypeScript dashboard.
- `output/` — assignment evidence, plans, reflection, screenshots, audit log, and repository URL.

## Setup

Python 3.10+ and Node.js are required. From this directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Add your own `PORTKEY_API_KEY` to `.env` before running live agent requests. The key is never included in this repository. Agents use the OpenAI `gpt-6-luna` model through Portkey.

Install and run the dashboard in a separate terminal:

```sh
cd frontend
npm install
npm run dev
```

Run the API in another terminal from the `backend/` directory:

```sh
cd backend
../.venv/bin/uvicorn main:app --reload --port 8000
```

Vite serves the dashboard at `http://localhost:5172`; the API is at `http://localhost:8000`. The API includes interactive documentation at `/docs`. The MCP server defaults to `data/campus_customs_new.db`; the optional `CAMPUS_CUSTOMS_DB` environment variable can override its path.

## Start the services

Start the components in this order. Python MCP/backend commands use the project virtual environment.

1. **MCP server** — with the virtual environment active, start the database tools:

   ```sh
   .venv/bin/python mcp_server/server.py
   ```

   The server uses `data/campus_customs_new.db` by default and speaks MCP over stdio. The FastAPI backend launches this same server as a subprocess for each tool session; the standalone command is for MCP clients/smoke testing, and should be stopped before using the integrated FastAPI flow to avoid confusion.

2. **FastAPI backend** — in a new terminal:

   ```sh
   cd backend
   ../.venv/bin/uvicorn main:app --reload --port 8000
   ```

3. **React dashboard** — in another terminal:

   ```sh
   cd frontend
   npm install
   npm run dev
   ```

   Open the Vite URL printed in the terminal (configured for `http://localhost:5172`). The backend is at `http://localhost:8000`.

4. **Reset before the full three-ticket run** — after the API is up and before running 101, 102, and 103, reset the working copy. This restores the original values and checking balance.

Before a fresh run across tickets 101, 102, and 103, restore the working copy from the untouched original. You can copy it manually from the project root:

```sh
cp data/campus_customs.db data/campus_customs_new.db
```

Or, with the API running, use its explicit reset route (the dashboard/API records the reset in the audit trail):

```sh
curl -X POST http://localhost:8000/api/database/reset \
  -H 'Content-Type: application/json' \
  -d '{"confirmation":"RESET WORKING DATABASE"}'
```

Either reset method overwrites the working database and its current ticket/payment state; it leaves the original database untouched. Check the starting checking balance, then run each open ticket once from the dashboard. The current `campus_customs_new.db` is the completed Problem 9 run, so resetting is necessary before repeating the full three-ticket run.

## Safety notes

The agent team only receives read-only MCP tools. Agents do not send email, contact vendors or landlords, resolve tickets, or make payments. The dashboard's explicit human approval routes perform supported database changes; they are not authentication and this development app should remain local. Never commit `.env` or paste its API key into source files.
