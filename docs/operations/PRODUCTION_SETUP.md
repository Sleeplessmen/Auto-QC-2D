# Production setup guide

This guide deploys the application with:

- Vercel for the static frontend.
- An Ubuntu VPS or cloud GPU instance for FastAPI, the review worker and
  model files.
- CVAT Cloud as the annotation platform.
- Docker Compose for the backend runtime.

Do not deploy the model worker as a Vercel Function. It needs persistent
processes, large model files, long-running jobs and usually a CUDA GPU.

## 1. Services and names

Use two hostnames:

| Purpose | Example |
| --- | --- |
| User-facing frontend | `https://app.example.com` |
| FastAPI backend | `https://api.example.com` |

The Vercel project rewrites `/api/*` to the backend. Users therefore stay on
the frontend hostname while browser requests are forwarded to FastAPI.

Use an object-storage bucket for backups and large artifacts. S3-compatible
storage, AWS S3 or Cloudflare R2 are suitable; the exact provider is an
operations choice and is not required by the application runtime.

## 2. Create accounts and credentials

Create or confirm:

1. A GitHub account with access to `Sleeplessmen/Auto-QC-2D`.
2. A Vercel project connected to that repository.
3. A domain and DNS provider.
4. A VPS/cloud GPU instance with a static public IPv4 address.
5. A CVAT Cloud organization and an account allowed to create/read Issues.
6. An object-storage bucket and a restricted backup credential.
7. An alert destination such as email, Slack or Teams.

In CVAT, create a personal access token with only the permissions required by
the QC workflow. Store it only on the backend. Never put `CVAT_TOKEN` in a
Vercel environment variable or frontend JavaScript.

## 3. Configure DNS

Create these DNS records:

```text
app.example.com  CNAME  <Vercel target shown by Vercel>
api.example.com  A      <VPS public IPv4>
```

Add both domains in Vercel and wait for the certificate to become active.
Configure TLS on the backend reverse proxy after DNS resolves to the VPS.

## 4. Provision the backend server

The commands below target Ubuntu 22.04/24.04. Run them as an administrative
user, then use the non-root deploy user for application operations.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git ufw nginx

sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
```

Install Docker Engine and the Compose plugin using Docker's official
instructions for the Ubuntu version. If GPU inference is required, also
install the matching NVIDIA driver and NVIDIA Container Toolkit, then verify:

```bash
docker --version
docker compose version
nvidia-smi
```

Create a deploy user and directories:

```bash
sudo adduser --disabled-password --gecos "" qcdeploy
sudo usermod -aG docker qcdeploy
sudo mkdir -p /opt/auto-qc-2d
sudo chown -R qcdeploy:qcdeploy /opt/auto-qc-2d
```

Log in again as `qcdeploy` so the Docker group is active, then clone the
repository at a release commit:

```bash
git clone https://github.com/Sleeplessmen/Auto-QC-2D.git /opt/auto-qc-2d
cd /opt/auto-qc-2d
git checkout <release-commit>
```

Do not deploy an unreviewed moving branch in production.

## 5. Create backend secrets and volumes

Copy the template and edit it on the server:

```bash
cd /opt/auto-qc-2d
cp .env.production.example .env.production
chmod 600 .env.production
nano .env.production
```

Set at least:

```dotenv
CVAT_URL=https://app.cvat.ai
CVAT_TOKEN=<CVAT personal access token>
CVAT_ORG=<CVAT organization slug if required>
WEB_QC_ADMIN_PASSWORD=<strong unique password>
QC_PUBLIC_BASE_URL=https://api.example.com
QC_CORS_ORIGINS=https://app.example.com
QC_SESSION_SAME_SITE=lax
QC_SESSION_SECURE=true
QC_DATA_DIR=/var/lib/auto-qc-2d/data
QC_REVIEW_OUTPUT_DIR=/var/lib/auto-qc-2d/review
QC_ARTIFACT_DIR=/var/lib/auto-qc-2d/artifacts
QC_MODEL_CACHE_DIR=/var/lib/auto-qc-2d/models
```

`QC_PUBLIC_BASE_URL` is used when generating labeler report links and webhook
URLs. It must be the public backend URL, not the Vercel URL.

The current Compose file creates named volumes for data, review output,
artifacts and model cache. For larger installations, replace named volumes
with mounted disks and monitor their free space.

## 6. Build and start FastAPI

Run from the repository root:

```bash
docker compose -f deploy/compose/docker-compose.production.yml config
docker compose -f deploy/compose/docker-compose.production.yml up -d --build
docker compose -f deploy/compose/docker-compose.production.yml ps
docker compose -f deploy/compose/docker-compose.production.yml logs --tail=200 qc
```

Verify locally on the VPS:

```bash
curl -fsS http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

The first startup creates the admin account and its temporary password file
inside the data volume. Log in once, change the password in Settings, and
remove the temporary file from the persistent data volume.

If the image fails during import because an ML package or model is missing,
do not bypass the failure. Add the missing runtime dependency/model download
to the image/build process, rebuild, and repeat the health check.

## 7. Configure HTTPS reverse proxy

Terminate TLS in Nginx, Caddy or Traefik and proxy only to
`127.0.0.1:8000`. A starting Nginx configuration is provided at
`deploy/reverse_proxy/nginx.conf.example`. Do not expose port 8000 publicly
after the proxy is working.

The proxy must support:

- HTTP to HTTPS redirect.
- `client_max_body_size` large enough for CVAT export uploads.
- Long read/send timeouts for review requests.
- `X-Forwarded-Proto`, `X-Forwarded-Host` and `X-Real-IP`.
- Access/error logs with rotation.
- Security headers.

Use the proxy's ACME integration (for example Let's Encrypt), then verify:

```bash
curl -fsS https://api.example.com/health
```

## 8. Configure Vercel

In Vercel:

1. Import `Sleeplessmen/Auto-QC-2D`.
2. Set **Root Directory** to `apps/web`.
3. Set **Output Directory** to `static`.
4. Leave the build command empty because the current frontend is dependency-free
   static JavaScript.
5. Add `app.example.com` as the production domain.
6. Edit `apps/web/vercel.json` and replace `api.example.com` with the real
   backend hostname before deploying.
7. Deploy a preview first, then promote the tested commit to production.

The rewrite in `apps/web/vercel.json` sends `/api/*` to FastAPI while keeping
the browser on the Vercel origin. This preserves same-origin cookie behavior.
If the architecture later switches to direct cross-origin API calls, set
`QC_CORS_ORIGINS` exactly to the Vercel production and preview origins and
keep `credentials: include`.

Verify:

```text
https://app.example.com/
https://app.example.com/#tab=settings
```

The login page must load, `/api/setup` must return successfully, and a failed
login must not expose a stack trace.

## 9. Connect CVAT Cloud

In the Web QC UI:

1. Log in as admin.
2. Open **Kết nối CVAT**.
3. Add the CVAT Cloud URL, organization and token.
4. Click **Thử kết nối**.
5. Save the connection and select it as default.
6. Select a test job and confirm that job metadata and annotations load.
7. Run a controlled review and push one test Issue.
8. Verify the Issue in CVAT, then verify duplicate protection on a second push.

For automatic validation review, enable it only after the manual flow works.
Move a non-production test job to validation and verify review, Issue creation
and the configured return-to-annotation behavior.

## 10. Backups and restore

Back up these items together because the database contains encrypted tokens
that require `secret.key`:

- `/var/lib/auto-qc-2d/data`
- `/var/lib/auto-qc-2d/review`
- Any external model manifest and model version metadata.

At minimum:

```bash
docker compose -f deploy/compose/docker-compose.production.yml stop qc
# Create a timestamped archive and upload it to restricted object storage.
tar -czf /tmp/auto-qc-2d-backup-$(date -u +%Y%m%dT%H%M%SZ).tgz \
  /var/lib/auto-qc-2d/data /var/lib/auto-qc-2d/review
docker compose -f deploy/compose/docker-compose.production.yml start qc
```

Use an automated encrypted backup job in production, retain multiple points
in time, and test restore on a separate machine. A backup is not considered
valid until a restore can start the application and decrypt the stored CVAT
connection.

## 11. Monitoring and operations

Monitor:

- `GET https://api.example.com/health`.
- Container restart count and application logs.
- Disk usage for data/review/model volumes.
- GPU memory/utilization and worker queue age.
- Review failures and CVAT API errors.
- HTTP 401/403/5xx rates.
- Last successful backup timestamp.

Useful commands:

```bash
docker compose -f deploy/compose/docker-compose.production.yml ps
docker compose -f deploy/compose/docker-compose.production.yml logs -f qc
docker stats
df -h
nvidia-smi
```

Do not delete `secret.key`, database files, review output or model cache while
debugging. Copy them to a backup first.

## 12. CI/CD and rollback

For every pull request, require:

```bash
python -m compileall -q apps packages web_qc tests/unit
python -m pytest -q
```

For a production deployment:

1. Merge only a reviewed commit to `main`.
2. Build and scan an immutable image tag based on the commit SHA.
3. Deploy that tag on the VPS.
4. Run `docker compose config`, container health and HTTPS smoke tests.
5. Run the controlled login/CVAT test.
6. Keep the previous image tag available.
7. If smoke tests fail, restore the previous tag and restart; do not mutate
   database files as a rollback shortcut.

Database/schema migrations must be backward-compatible with the previous
application image before deployment.

## 13. Go-live checklist

- [ ] Vercel production domain and HTTPS active.
- [ ] Backend domain and HTTPS active.
- [ ] `/health` returns `{"status":"ok"}` over HTTPS.
- [ ] Frontend login and session cookie work after refresh.
- [ ] Admin password changed and temporary password file removed.
- [ ] CVAT token stored only in backend.
- [ ] Manual review and Issue push verified.
- [ ] Automatic validation flow verified on a test job.
- [ ] Persistent data and model volumes mounted.
- [ ] Backup completed and restore tested.
- [ ] Monitoring and alert destination tested.
- [ ] Previous image tag recorded for rollback.
