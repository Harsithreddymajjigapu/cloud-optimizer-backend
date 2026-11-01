# ☁️ Cloud Optimizer Backend

A backend API that discovers the virtual machines in a customer's Azure
subscription, measures their real CPU usage through **Azure Monitor**, and asks
**Google Gemini** whether each one is correctly sized — returning a
recommendation, an estimated monthly saving, and the exact `az` command to
apply the fix.

---

## 🏗️ How it works

The API and the analysis never wait on each other. A request that had to call
Azure and Gemini inline would hold the connection open for half a minute and
fail whenever either service was slow.

```
POST /api/v1/accounts/sync
        │
        ├─ verify the caller's JWT
        ├─ publish a job to Redis
        └─ return 202 immediately          ← Azure has not been contacted yet

Celery worker picks the job up
        │
        ├─ decrypt the stored client secret        crypto.py
        ├─ list the subscription's VMs             azure_client.py → Azure Compute
        ├─ read 7 days of "Percentage CPU"         azure_client.py → Azure Monitor
        ├─ save / refresh each VM                  models.CloudResource
        └─ queue one analysis job per VM

Analysis job
        │
        ├─ ask Gemini for a verdict                ai_analyst.py
        │     └─ if Gemini is unavailable, fall back to a rule-based sentence
        └─ write an OptimizationAlert              models.OptimizationAlert

GET /api/v1/alerts        → the recommendations, scoped to the caller
```

---

## ⚙️ Tech stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI |
| Database | PostgreSQL + SQLAlchemy |
| Task queue | Celery + Redis |
| AI | Google Gemini 2.5 Flash (structured output via a Pydantic schema) |
| Cloud metrics | Azure SDK — Compute + Monitor |
| Auth | JWT (python-jose) |
| Secrets at rest | Fernet (`cryptography`) |
| Containers | Docker Compose — web, worker, beat, redis, db |

---

## 🚀 Running it

### 1. Clone

```bash
git clone https://github.com/Harsithreddymajjigapu/cloud-optimizer-backend
cd cloud-optimizer-backend
```

### 2. Create `.env`

```env
DATABASE_URL=postgresql+psycopg2://postgres:yourpassword@db:5432/cloud_db
POSTGRES_PASSWORD=yourpassword
CELERY_BROKER_URL=redis://redis:6379/0
SECRET_KEY=your_jwt_signing_key
ENCRYPTION_KEY=generate_this_see_below
GEMINI_API_KEY=your_gemini_api_key
```

`DATABASE_URL` must name the driver (`+psycopg2`). SQLAlchemy 2.1 changed what a
bare `postgresql://` means — it now resolves to psycopg3, which is not a
dependency of this project.

Generate `ENCRYPTION_KEY` with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Start everything

```bash
docker compose up -d
```

Five containers: `web`, `worker`, `beat`, `redis`, `db`.
Swagger UI at <http://localhost:8000/docs>.

### 4. Use it

1. `POST /auth/register`, then **Authorize** in Swagger (the username field takes your email)
2. `POST /api/v1/accounts/link-azure` with tenant, client, secret and subscription IDs
3. `POST /api/v1/accounts/sync`
4. `GET /api/v1/alerts`

---

## 📡 API

### Auth
| Method | Endpoint | Description |
|---|---|---|
| POST | `/auth/register` | Create an account |
| POST | `/auth/login` | Exchange email + password for a JWT |
| GET | `/auth/me` | The current account |

### Azure accounts
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/accounts/link-azure` | Link a subscription — credentials are verified against Azure before being stored |
| GET | `/api/v1/accounts` | List linked subscriptions (never returns the secret) |
| PUT | `/api/v1/accounts/{id}` | Rotate an expired client secret |
| DELETE | `/api/v1/accounts/{id}` | Unlink and discard the stored credentials |
| POST | `/api/v1/accounts/sync` | Queue a scan — returns 202 |

### Resources and alerts
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/resources` | VMs discovered for the caller |
| GET | `/api/v1/alerts` | Recommendations for the caller |
| POST | `/servers/` | Register a resource manually, with usage figures you supply |

Every endpoint requires a token and returns only the caller's own data.

---

## ⏰ Scheduled scans

The `beat` container queues `tasks.sync_all_accounts` once an hour. That task
finds every user with a linked subscription and queues one sync job each,
rather than a single long job where one slow subscription would stall the rest.

The interval is `SYNC_INTERVAL_MINUTES` (default 60).

---

## 🔐 Azure App Registration setup

This tool only ever reads, so the App Registration should be granted the
minimum that allows reading:

| Role | Scope | Why |
|---|---|---|
| **Reader** | Subscription | List virtual machines and their sizes |
| **Monitoring Reader** | Subscription | Read `Percentage CPU` from Azure Monitor |

Do **not** grant Contributor or Owner — a broader role would mean the stored
credentials could modify or delete infrastructure.

1. Entra ID → App registrations → New registration
2. Certificates & secrets → New client secret (note the expiry)
3. Subscription → Access control (IAM) → Add role assignment → **Reader** → the app
4. Repeat for **Monitoring Reader**
5. Supply the four IDs to `POST /api/v1/accounts/link-azure`

Client secrets expire (24 months at most). When one does, rotate it in Azure and
send the new value to `PUT /api/v1/accounts/{id}` — the other fields can be
omitted.

### Credential storage

Client secrets are encrypted with Fernet before being written to the database.
The key lives in `ENCRYPTION_KEY` and never in the database, so a database dump
on its own cannot be used to reach a customer's cloud.

Changing the key makes every stored secret undecryptable and forces all
customers to re-link, so treat it as long-lived.

---

## 🧪 Tests

```bash
pytest tests/ -v
```

25 tests. They run against SQLite by default (no database needed) and against
PostgreSQL in CI, with foreign keys enforced in both.

```
tests/
├── conftest.py          environment and a clean schema for every run
├── test_main.py         8   endpoints, auth, CRUD
├── test_pipeline.py     11  link → sync → metrics → alert, with Azure faked
└── test_isolation.py    6   one user must not see another user's data
```

Only the boundaries to Azure and Gemini are mocked. Everything inside the
project — the endpoints, JWT auth, encryption, the Celery tasks, the database
writes — runs for real.

Several tests exist because a specific bug reached production once and must not
return:

| Test | The bug it guards |
|---|---|
| `test_full_pipeline_writes_an_alert` | A wrong model name meant no alert was ever written, for four months, with no error |
| `test_sync_sends_a_valid_timespan_to_azure` | `isoformat()` emits `+00:00`; `+` decodes as a space in a URL, and Azure rejected every metrics call |
| `test_link_rejects_malformed_tenant_id` | A typo'd GUID returned a 500 stack trace instead of a readable 400 |
| `test_vm_with_no_metrics_is_skipped` | A deallocated VM reports no data — that must read as "unknown", not "idle" |
| `tests/test_isolation.py` | Any logged-in user could read every other user's resources and recommendations |

---

## 📁 Project structure

```
cloud-optimizer-backend/
├── main.py              FastAPI app and every HTTP endpoint
├── auth.py              register, login, JWT issue and verify
├── schemas.py           Pydantic models — what goes in and out
├── models.py            SQLAlchemy tables
├── database.py          engine, session factory, Base
├── crypto.py            Fernet encrypt/decrypt for client secrets
├── azure_client.py      the only file that talks to Azure
├── ai_analyst.py        the only file that talks to Gemini
├── tasks.py             Celery tasks — sync, analyse, scheduled fan-out
├── worker.py            Celery entry point and configuration
├── Dockerfile
├── docker-compose.yml   web, worker, beat, redis, db
├── requirements.txt
└── tests/
```

---

## 🔑 API keys

- **Gemini** → [Google AI Studio](https://aistudio.google.com)
- **Azure** → [Azure Portal](https://portal.azure.com)

---

## 👤 Author

Harsith Reddy Majjigapu