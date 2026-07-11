# Production deployment — Linux VPS

This guide deploys **meme_gen** on a Linux VPS behind **nginx** with **Let's Encrypt** TLS, served by **gunicorn** managing multiple **uvicorn** workers.

Target domain in the bundled configs: **`vid.abdspros.com`**.

## Architecture

```
Internet ──443──▶ nginx (TLS, Let's Encrypt) ──127.0.0.1:8000──▶ gunicorn (N uvicorn workers) ─▶ FastAPI app
                                                                                      │
                                                              each worker runs render threads
                                                                                      │
                                                            all workers share meme_gen.db (SQLite WAL)
```

- **gunicorn** is the process manager; each worker is an `uvicorn.workers.UvicornWorker` serving the FastAPI ASGI app.
- **Multi-worker safety**: `app/db.py` enables SQLite WAL mode + a 5s busy timeout, so N worker processes share one DB file without "database is locked" errors. Each worker also runs its own background render threads, so total concurrency ≈ workers × in-flight renders.
- **nginx** terminates TLS and proxies to gunicorn on loopback only — uvicorn is never directly exposed.
- Renders stay in-process (threading, not an external task queue) by design; this keeps the stack simple (no Postgres/Redis required).

---

## 1. System packages

On the VPS (Debian/Ubuntu):

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx python3-venv ffmpeg ufw
```

`ffmpeg` is required by MoviePy / `ffprobe` (used by `app/clip_source.py`).

## 2. Get the code onto the VPS

```bash
sudo mkdir -p /srv/meme_gen
sudo chown "$USER":"$USER" /srv/meme_gen
git clone <your-repo-url> /srv/meme_gen
cd /srv/meme_gen
```

## 3. Python environment + dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 4. Create the `.env`

Copy your local `.env` (the one with the real API keys) to `/srv/meme_gen/.env`. **Two things you must change for production:**

```bash
# /srv/meme_gen/.env
SECRET_KEY=<generate a strong random key, e.g. `python3 -c "import secrets;print(secrets.token_hex(32))"`>
ADMIN_PASSWORD=<a strong password>

GIPHY_API_KEY=...
KLIPY_API_KEY=...
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=...
# Optional tuning (defaults shown):
# HOST=127.0.0.1
# PORT=8000
# WEB_CONCURRENCY=4
```

```bash
sudo chmod 600 /srv/meme_gen/.env   # it contains secrets
```

If the app prints `WARNING: SECRET_KEY is the insecure default…` on startup, you forgot to set it.

## 5. Create a dedicated service user

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin memegen
sudo chown -R memegen:memegen /srv/meme_gen
```

## 6. Log directory

`deploy/gunicorn_conf.py` writes logs to `/var/log/meme_gen/`:

```bash
sudo mkdir -p /var/log/meme_gen
sudo chown -R memegen:memegen /var/log/meme_gen
```

## 7. Install the nginx site

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/vid.abdspros.com
sudo ln -sf /etc/nginx/sites-available/vid.abdspros.com /etc/nginx/sites-enabled/vid.abdspros.com

# Remove the default site if it conflicts for port 80:
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t
```

> **Order matters**: run `certbot` (next step) **before** reloading nginx, because the `:443` block references cert files that don't exist yet. `certbot --nginx` will issue the cert and reload nginx for you.

## 8. Point the domain + issue the TLS certificate

1. Create an **A record** for `vid.abdspros.com` → your VPS public IP. Wait for DNS to propagate (`dig vid.abdspros.com`).

2. Issue the certificate (certbot rewrites the nginx config for you):

```bash
sudo certbot --nginx -d vid.abdspros.com
```

3. Reload nginx to be safe:

```bash
sudo systemctl reload nginx
```

Certbot installs a systemd timer for automatic renewal — no further action needed.

## 9. Install the systemd service

```bash
sudo cp deploy/meme_gen.service /etc/systemd/system/meme_gen.service
sudo systemctl daemon-reload
sudo systemctl enable --now meme_gen
```

## 10. Firewall

Open only the public-facing ports. **Do not** open 8000 — uvicorn must stay loopback-only.

```bash
sudo ufw allow OpenSSH
sudo ufw allow "Nginx Full"     # 80 + 443
sudo ufw enable
```

---

## Verification

```bash
# 1. The app answers on loopback (run on the VPS):
curl -I http://127.0.0.1:8000/                # expect 200 OK

# 2. The service is healthy:
systemctl status meme_gen
sudo journalctl -u meme_gen -f                # live logs

# 3. Public HTTPS works (from your machine):
curl -I https://vid.abdspros.com/             # expect 200 + TLS

# 4. HTTP redirects to HTTPS:
curl -I http://vid.abdspros.com/              # expect 301 → https

# 5. Access/error logs:
sudo tail -f /var/log/meme_gen/access.log
sudo tail -f /var/log/meme_gen/error.log
sudo tail -f /var/log/nginx/error.log
```

## Operating the service

```bash
sudo systemctl restart meme_gen      # restart workers (picks up new code after git pull)
sudo systemctl reload  meme_gen      # graceful HUP — wait, see note below
sudo systemctl status   meme_gen
```

> **Reload caveat**: gunicorn graceful reload (`systemctl reload`) signals workers to exit once idle. Because render threads are in-process, a reload can interrupt in-flight renders. Prefer `restart` during low-traffic windows, or accept that an active render may move to `failed` and the user can retry.

To deploy a code update:

```bash
cd /srv/meme_gen
git pull
source venv/bin/activate
pip install -r requirements.txt     # only if deps changed
sudo systemctl restart meme_gen
```

## Tuning concurrency

- `WEB_CONCURRENCY` (env var, default `4`): number of gunicorn/uvicorn worker processes. Set roughly to CPU core count. Each worker can run multiple concurrent renders via its own threads.
- `PORT` (default `8000`): uvicorn bind port. If you change it, also change the `proxy_pass` line in the nginx config.

## Migrating to Postgres (optional, for heavier load)

SQLite + WAL handles moderate multi-user load well. If you outgrow it:

1. Provision Postgres, create a DB + user.
2. Set `DATABASE_URL=postgresql+psycopg://user:pass@localhost/meme_gen` in `.env`.
3. `pip install psycopg[binary]`.
4. `systemctl restart meme_gen`. The connect listener in `app/db.py` is a no-op for non-SQLite engines.

## Files in this directory

| File | Purpose |
|---|---|
| `gunicorn_conf.py` | Worker config (bind, workers, timeouts, proxy headers, log paths) |
| `nginx.conf` | nginx site config (HTTP→HTTPS, TLS, reverse proxy) |
| `meme_gen.service` | systemd unit (auto-restart, hardening) |
| `README.md` | This file |


## ADDITIONAL NOTES
- Make sure to open ports 80, 443 in hostinger as well.
- Certbot may rewrite your configuration and removed your proxy configuration, replacing it with a redirect-only HTTPS server. Use 'sudo certbot renew' instead of the cert already exists
- Need to reload ngnix if making code changes "sudo systemctl reload meme_gen'