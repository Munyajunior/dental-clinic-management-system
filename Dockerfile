# Production-ready Dockerfile (starter)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for building some Python packages and postgres client headers
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata first for better layer caching
COPY pyproject.toml ./
COPY src ./src
COPY .env.production.example .env

RUN python -m pip install --upgrade pip
# If you maintain a requirements.txt, it will be used. Otherwise install core packages as fallback.
RUN if [ -f requirements.txt ]; then pip install -r requirements.txt; else pip install fastapi uvicorn sqlalchemy asyncpg alembic; fi

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
