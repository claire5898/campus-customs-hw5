# Campus Customs Agent Dashboard

React, Vite, and TypeScript dashboard for the local Campus Customs API.

## Run locally

Start the FastAPI backend first at `http://localhost:8000` (see `../backend/README.md`). Then:

```sh
npm install
npm run dev
```

Open `http://localhost:5172`. The dashboard calls the FastAPI backend directly at `http://localhost:8000`; the backend allows this Vite origin through CORS. You can override the API URL with `VITE_API_BASE_URL` if needed.

The dashboard polls ticket status, checking balance, and recent audit events. Starting a run shows agent and MCP-tool progress while the ticket-specific request is running. Payment and purchase actions require typed confirmation and a human name; the purchase endpoint records a cash outflow only and does not place a vendor order. After reviewing the Boss report, a human may explicitly mark an open ticket resolved. Agents never change ticket status.

This is a local homework interface. The approval name and typed phrase are not authentication; do not expose it to a network or use it for real financial operations.
