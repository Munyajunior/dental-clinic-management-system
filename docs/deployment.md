# Deployment Guide — Dental Clinic Management System

This document contains recommended, low-risk deployment steps and production best practices for the FastAPI backend.

1) Build and packaging

- Prefer running the app as a container in production. Create a small production Docker image (use `python:3.13-slim` base).
- Keep build-time and run-time secrets separated. Do not bake secrets into images.

2) Environment and secrets

- Use a secrets manager (Vault, AWS Secrets Manager, Azure Key Vault) to inject secrets at runtime.
- Use environment variables for configuration (see `.env.production.example`).
- Required secrets (examples): `DB_USER`, `DB_PASSWORD`, `SECRET_KEY`, `STRIPE_SECRET_KEY`, `REDIS_PASSWORD`, `FILE_ENCRYPTION_KEY`.

3) Database & Migrations

- Use PostgreSQL for production. The app uses async SQLAlchemy with `asyncpg`.
- Run migrations with Alembic before starting the service:

```powershell
# from project root (PowerShell)
.venv\Scripts\Activate.ps1
alembic upgrade head
```

- Ensure connection pool settings and `pool_pre_ping=True` are enabled (see `src/db/database.py`).
- Use a single migration runner in blue/green deploys to avoid race conditions.

4) Running the app

- Use a process manager or container orchestration (systemd, Docker Compose, Kubernetes).
- Example `uvicorn` production command (inside container):

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4 --limit-concurrency 100 --timeout-keep-alive 30
```

- For Kubernetes, use a readinessProbe and livenessProbe that call `/api/v2/health`.

5) Scaling and performance

- Use multiple Uvicorn workers (one per CPU core) and scale horizontally.
- Use Redis (if `REQUIRE_REDIS` / `CACHE_ENABLED`) for caching and rate-limiter state.
- Monitor connection pool usage (asyncpg) and tune `pool_size`/`max_overflow` accordingly.

6) Security

- Enforce TLS termination at the edge (load balancer or ingress controller).
- Store `SECRET_KEY`, `FILE_ENCRYPTION_KEY` and payment keys in a secrets manager.
- Use proper firewall rules for DB access (only allow the app hosts).
- Validate CORS (`ALLOWED_ORIGINS`) for production and set to specific origins.

7) Multi-tenancy & RLS

- Row Level Security (RLS) is enabled by `setup_rls()` in `src/db/database.py`.
- Ensure the DB role used by the app has sufficient privileges to create policies during initial setup or run RLS setup as a separate administrative step.

8) Backups & DR

- Schedule regular DB backups and test restore procedures.
- Back up tenant-specific files stored under `MEDICAL_RECORDS_STORAGE_PATH`.

9) Observability

- Ship logs to a centralized logging system (ELK, Datadog, etc.).
- Use health endpoints (`/api/v2/health`, `/api/v2/startup-check`) for monitoring.
- Add instrumentation (Prometheus metrics, tracing) as needed.

10) CI/CD

- Run unit tests and linting in CI.
- Run a pre-deploy migration check in CI to ensure no conflicting schema changes.

# Quick checklist before first release

- [ ] Secrets moved to a secrets manager
- [ ] Alembic migrations applied
- [ ] TLS configured
- [ ] Backups scheduled
- [ ] Monitoring and logging configured
