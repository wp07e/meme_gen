"""Gunicorn production config for the meme_gen FastAPI app.

Run as:
    gunicorn app.main:app -c deploy/gunicorn_conf.py

Architecture notes
------------------
- worker_class = uvicorn.workers.UvicornWorker serves the FastAPI ASGI app.
- workers > 1 is SAFE because app/db.py enables SQLite WAL + busy_timeout, so
  every worker process shares the same meme_gen.db without "database is
  locked" errors. Each worker also runs its own render threads (spawned by
  app/main.py's /api/render route), so total concurrency ≈ workers × threads.
- forwarded_allow_ips="*" plus UvicornWorker's proxy-headers handling lets the
  app see X-Forwarded-Proto from nginx, so login cookies are flagged Secure
  behind TLS (see app/main.py: api_login uses request.url.scheme).
- bind stays on 127.0.0.1: nginx is the only public listener.
- No max_requests: recycling a worker would abort any in-flight render thread.
- preload_app=False: each worker runs FastAPI's startup hook (idempotent DB
  init/migrations) independently, which is the correct behavior for forked
  workers sharing a DB.
"""
import os

_HOST = os.getenv("HOST", "127.0.0.1")
_PORT = os.getenv("PORT", "8000")

# ASGI serving
worker_class = "uvicorn.workers.UvicornWorker"

# Concurrency: tune with the WEB_CONCURRENCY env var. Each worker is a full
# process running its own render threads, so 2-4 workers typically covers a
# small multi-user load. Match roughly to (CPU cores).
workers = int(os.getenv("WEB_CONCURRENCY", "4"))

# Trust proxy headers from nginx so X-Forwarded-Proto → Secure cookies.
forwarded_allow_ips = "*"

# Loopback only — nginx proxies public traffic to this address.
bind = [f"{_HOST}:{_PORT}"]

# Long requests: a render can take 30-60s; allow generous headroom.
timeout = 300
graceful_timeout = 300
keepalive = 5

# Logging (create these paths on the VPS; see deploy/README.md).
accesslog = "/var/log/meme_gen/access.log"
errorlog = "/var/log/meme_gen/error.log"
loglevel = "info"

# Do NOT set max_requests — recycling would kill in-flight render threads.
preload_app = False
