#!/bin/bash
# Unified ibkr-proxy entrypoint.
#
# Starts IB Gateway + IBC in the background, waits for the API socket to
# become reachable, and then execs uvicorn so the FastAPI process inherits
# PID 1.
#
# IB Gateway binds its API to 127.0.0.1 only, so we wait on the loopback
# port (4002 for paper, 4001 for live) rather than the socat-relayed port
# (4004 / 4003).

set -Eeo pipefail

# Resolve the loopback API port from TRADING_MODE. Default to paper.
TRADING_MODE="${TRADING_MODE:-paper}"
case "${TRADING_MODE}" in
    live)
        IB_API_PORT="${IB_API_PORT:-4001}"
        ;;
    paper|*)
        IB_API_PORT="${IB_API_PORT:-4002}"
        ;;
esac

IB_API_READY_TIMEOUT="${IB_API_READY_TIMEOUT:-180}"

echo "==> Starting IB Gateway + IBC in background (TRADING_MODE=${TRADING_MODE})"
bash /home/ibgateway/scripts/run.sh &
IBGW_PID=$!
trap 'echo "==> Stopping IB Gateway"; kill -TERM ${IBGW_PID} 2>/dev/null || true; wait' TERM INT

echo "==> Waiting for IB Gateway API on 127.0.0.1:${IB_API_PORT} (timeout=${IB_API_READY_TIMEOUT}s)"
deadline=$((SECONDS + IB_API_READY_TIMEOUT))
while (( SECONDS < deadline )); do
    if bash -c "</dev/tcp/127.0.0.1/${IB_API_PORT}" >/dev/null 2>&1; then
        echo "==> IB Gateway API reachable"
        break
    fi
    sleep 1
done

if ! bash -c "</dev/tcp/127.0.0.1/${IB_API_PORT}" >/dev/null 2>&1; then
    echo "!! IB Gateway API did not become ready in ${IB_API_READY_TIMEOUT}s" >&2
    exit 1
fi

echo "==> Launching ibkr-proxy"
exec "$@"
