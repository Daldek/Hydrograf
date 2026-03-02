# ============================================================
# Stage 1: builder — install build tools and compile deps
# ============================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# Build-time system dependencies (gcc, git for git+https:// pip deps)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    libgeos-dev \
    libproj-dev \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ============================================================
# Stage 2: runtime — lean production image
# ============================================================
FROM python:3.12-slim

WORKDIR /app

# Runtime-only system libraries (no compilers, no git)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libgeos-c1t64 \
    libproj25 \
    libexpat1 \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built virtualenv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY . .

# Ensure entrypoint is executable
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
