# syntax=docker/dockerfile:1

FROM node:22-alpine AS frontend-builder

WORKDIR /build
COPY apps/market-environment-dashboard/package.json \
     apps/market-environment-dashboard/package-lock.json \
     apps/market-environment-dashboard/
RUN npm ci --prefix apps/market-environment-dashboard

COPY apps/market-environment-dashboard apps/market-environment-dashboard
RUN npm run build --prefix apps/market-environment-dashboard


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp \
    TZ=Asia/Shanghai

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --no-create-home --uid 10001 --user-group app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY --chown=10001:10001 src ./src
COPY --from=frontend-builder --chown=10001:10001 \
     /build/apps/market-environment-dashboard/dist \
     ./apps/market-environment-dashboard/dist

USER 10001:10001
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "src.market_environment.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
