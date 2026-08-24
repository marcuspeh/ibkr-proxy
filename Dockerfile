# syntax=docker/dockerfile:1.7
#
# Unified image for ibkr-proxy.
#
# Layered on top of ghcr.io/gnzsnz/ib-gateway:latest, which already brings:
#   - Ubuntu 24.04 with Xvfb, IBC, socat, sshpass, sudo
#   - IB Gateway binary + IBC bootstrap scripts under /home/ibgateway
#   - socat that forwards the IB Gateway API to 0.0.0.0:4004 (paper)
#     or 0.0.0.0:4003 (live)
#
# We only add Python + uv + the FastAPI proxy on top. docker-entrypoint.sh
# starts IB Gateway + IBC in the background, waits for the API socket, and
# then execs uvicorn so both processes share the same container but stay
# loosely coupled. Python deps are managed with uv and pinned via uv.lock.

ARG IB_GATEWAY_IMAGE=ghcr.io/gnzsnz/ib-gateway:latest

FROM ${IB_GATEWAY_IMAGE} AS base

# Install Python (Ubuntu 24.04 ships python3.12), uv, and the small
# toolchain the proxy needs.
USER root
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update -y \
 && apt-get install --no-install-recommends --yes \
        python3.12 python3.12-venv python3.12-dev \
        build-essential ca-certificates curl \
 && ln -sf /usr/bin/python3.12 /usr/bin/python3 \
 && ln -sf /usr/bin/python3.12 /usr/bin/python \
 && curl -sSfL https://github.com/astral-sh/uv/releases/download/0.5.11/uv-installer.sh \
    | env UV_UNMANAGED_INSTALL=/usr/local/bin sh \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Drop back to the ibgateway user so the app layer matches upstream's
# permission model (the home directory is writable).
USER 1000:1000
WORKDIR /home/ibgateway/app

ENV PATH="/home/ibgateway/app/.venv/bin:${PATH}" \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/home/ibgateway/app/.venv \
    PYTHONPATH=/home/ibgateway/app

# ---------- builder ----------
FROM base AS builder

# Copy only the project metadata first so the dependency install is cached.
COPY --chown=1000:1000 pyproject.toml uv.lock /home/ibgateway/app/
RUN uv sync --frozen --no-install-project

# Then copy the source and install the project itself (no dev deps).
COPY --chown=1000:1000 . /home/ibgateway/app
RUN uv sync --frozen --no-dev

# ---------- runtime ----------
FROM base AS runtime

COPY --chown=1000:1000 --from=builder /home/ibgateway/app /home/ibgateway/app

# Entrypoint waits for the API socket, then launches uvicorn.
RUN chmod +x /home/ibgateway/app/docker-entrypoint.sh

# In-container port for the FastAPI proxy. IB Gateway paper API is exposed
# on 127.0.0.1:4002 inside the container (or 4001 for live). The host port
# mapping is configured in docker-compose.yml.
EXPOSE 5001

ENV PORT_API=5001 \
    IB_API_READY_TIMEOUT=180

ENTRYPOINT ["/home/ibgateway/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5001"]
