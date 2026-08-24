# IBKR Broker Proxy

A standalone Python FastAPI service that bridges external trading clients with Interactive Brokers (IBKR) using the `ib_async` library.

Packaged as a single Docker image layered on top of [`ghcr.io/gnzsnz/ib-gateway`](https://github.com/gnzsnz/ib-gateway-docker) so the proxy and IB Gateway live together in one container — the recommended setup for one proxy per IBKR account.

## Features

- **Asynchronous Execution**: Built on `ib_async` and FastAPI for high-performance, non-blocking I/O.
- **Unified Order API**: Simplified endpoints for Market, Limit, and complex Bracket orders.
- **Real-time Webhooks**: Pushes fill details and order status updates to a configured external webhook URL.
- **Idempotency**: Supports `X-Idempotency-Key` headers to prevent duplicate order placement during retries.
- **State Synchronization**: Endpoints to fetch current positions, open orders, and system health.
- **Automatic Session Management**: Handles heartbeats ("tickles") and reconnection logic to keep the IBKR session alive.
- **Single-container deploy**: Proxy + IB Gateway boot together via `docker-entrypoint.sh`, which waits for the IB Gateway API socket before launching uvicorn.

## Prerequisites

- Docker with Compose v2.
- An IBKR account with API access enabled.
- IBKR credentials (`TWS_USERID`, `TWS_PASSWORD`). Paper trading accounts work out of the box.

## Quick start (Docker)

1. Copy the example env file and fill in your IBKR credentials:

   ```bash
   cp .env.example .env
   # edit .env: set TWS_USERID and TWS_PASSWORD
   ```

2. Build and run:

   ```bash
   docker compose up --build
   ```

   The entrypoint starts IB Gateway + IBC in the background, waits up to `IB_API_READY_TIMEOUT` seconds (default 180s) for the API socket on `127.0.0.1:4002` (paper) or `127.0.0.1:4001` (live), then `exec`s uvicorn. After it's up, the proxy listens on `http://localhost:5001` and the OpenAPI docs are at `http://localhost:5001/docs`.

3. Check health:

   ```bash
   curl http://localhost:5001/health
   ```

## Running multiple proxies

Each proxy assumes it is the **only** client connected to its IB Gateway (single active proxy per container). To run more than one proxy per IBKR account, deploy additional stacks with a unique `IBKR_CLIENT_ID` and a unique host port mapping:

```yaml
# stack #2
services:
  ibkr-proxy:
    environment:
      IBKR_CLIENT_ID: 2
    ports:
      - "5002:5001"
```

If you genuinely need multiple proxies sharing one IB Gateway, split the image into a separate `ib-gateway` service and a `proxy` service on a shared network. The Dockerfile and entrypoint already support that mode (the proxy just talks to `127.0.0.1:4002` inside its container).

## Configuration

Configuration is managed via environment variables or a `.env` file.

### Proxy

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_PORT` | Host port the FastAPI proxy is published on | `5001` |
| `IBKR_HOST` | Host of the IB Gateway API (loopback inside the container) | `127.0.0.1` |
| `IBKR_PORT` | IB Gateway API port (set by entrypoint from `TRADING_MODE`) | `4002` (paper) / `4001` (live) |
| `IBKR_CLIENT_ID` | Unique client id per concurrent proxy | `1` |
| `WEBHOOK_URL` | External URL to push fills/status updates (leave blank to disable) | `""` |

### IB Gateway (`gnzsnz/ib-gateway`)

| Variable | Description | Default |
|----------|-------------|---------|
| `TWS_USERID` | IBKR username | **required** |
| `TWS_PASSWORD` | IBKR password (use `TWS_PASSWORD_FILE` for Docker secrets) | **required** |
| `TRADING_MODE` | `live` or `paper` | `paper` |
| `VNC_SERVER_PASSWORD` | Enables VNC on host port 5900 if set | unset |
| `TWOFA_TIMEOUT_ACTION` | `exit` or `restart` | `restart` |
| `RELOGIN_AFTER_TWOFA_TIMEOUT` | `yes`/`no` | `yes` |
| `TIME_ZONE` | Container timezone | `Etc/UTC` |
| `IB_API_READY_TIMEOUT` | Seconds to wait for the API socket | `180` |

See the [gnzsnz/ib-gateway docs](https://github.com/gnzsnz/ib-gateway-docker) for the full set of variables (Docker secrets, `READ_ONLY_API`, etc.).

## Usage (local, no Docker)

Python deps are managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync
export IBKR_HOST=127.0.0.1 IBKR_PORT=4002 IBKR_CLIENT_ID=1
uv run python -m app.main
```

Or activate the venv directly:

```bash
source .venv/bin/activate
python -m app.main
```

## API Endpoints

- `GET /health`: Check connection status to IBKR.
- `GET /positions`: List all current holdings.
- `GET /account/nav`: Get current account Net Liquidation Value (NAV).
- `GET /orders/open`: List all active/open orders.
- `GET /ohlc`: Get OHLC data for a list of tickers for the current day.
- `POST /orders/market`: Place a market order.
- `POST /orders/limit`: Place a limit order.
- `POST /orders/bracket`: Place a three-part bracket order (Entry, TP, SL). All components have **Outside Regular Trading Hours** enabled. The **Entry** order is set to **DAY**, while **TP** and **SL** are set to **GTC**.
- `PUT /orders/{order_id}`: Update an existing order's price (Limit or Stop) or quantity.
- `DELETE /orders/{order_id}`: Cancel an active order.

## Webhooks

If `WEBHOOK_URL` is set, the proxy pushes JSON payloads to `{WEBHOOK_URL}/fills` and `{WEBHOOK_URL}/status`.

### Example Fill Payload
```json
{
  "permId": 123456789,
  "execId": "00012345.6789",
  "fillPrice": 150.25,
  "fillQty": 100,
  "orderRef": "strategy_abc",
  "commission": 1.0
}
```

## Layout

```
ibkr-proxy/
├── Dockerfile             # FROM ghcr.io/gnzsnz/ib-gateway:latest
├── docker-entrypoint.sh   # boots IB Gateway, waits for API, execs uvicorn
├── docker-compose.yml
├── pyproject.toml         # uv-managed Python deps
├── uv.lock
├── .dockerignore
├── .env.example
└── app/
    ├── __init__.py
    ├── main.py            # FastAPI app (run as app.main:app)
    ├── ibkr_client.py     # ib_async wrapper + webhook fan-out
    ├── config.py          # pydantic settings
    └── models.py          # pydantic request/response models
```
