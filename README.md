# ☁️ Cloud Optimizer Backend

A backend API that monitors your cloud servers, analyzes their CPU usage using **Azure Monitor**, and generates cost-saving recommendations using **Google Gemini AI**.

---

## 🏗️ Architecture

---

## ⚙️ Tech Stack

| Layer | Technology |
|---|---|
| Web Framework | FastAPI |
| Database | PostgreSQL + SQLAlchemy |
| Task Queue | Celery + Redis |
| AI | Google Gemini 2.5 Flash |
| Cloud Metrics | Azure Monitor SDK |
| Auth | JWT (python-jose) |
| Validation | Pydantic |

---

## 🚀 Getting Started

### 1. Clone the Repository
```bash
git clone https://github.com/Harsithreddymajjigapu/cloud-optimizer-backend
cd cloud-optimizer-backend
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Set Up Environment Variables
Create a `.env` file in the root directory:
```env
DATABASE_URL=postgresql://username:password@localhost:5432/cloudoptimizer
REDIS_URL=redis://localhost:6379/0
GEMINI_API_KEY=your_gemini_api_key_here
SECRET_KEY=your_jwt_secret_key_here
```

### 5. Set Up PostgreSQL Database
```bash
psql -U postgres
CREATE DATABASE cloudoptimizer;
\q
```

### 6. Start Redis
```bash
docker run -d -p 6379:6379 redis
```

### 7. Start the FastAPI Server
```bash
uvicorn main:app --reload
```

### 8. Start the Celery Worker (separate terminal)
```bash
celery -A Worker worker --loglevel=info --pool=solo
```

---

## 📡 API Endpoints

### Authentication
| Method | Endpoint | Description |
|---|---|---|
| POST | `/auth/register` | Register new user |
| POST | `/auth/login` | Login and get JWT token |

### Users
| Method | Endpoint | Description |
|---|---|---|
| POST | `/users/` | Create a new user |
| GET | `/users/` | Get all users |

### Servers
| Method | Endpoint | Description |
|---|---|---|
| POST | `/servers/` | Register a cloud server (triggers AI analysis) |
| GET | `/servers/` | Get all registered servers |

### Alerts
| Method | Endpoint | Description |
|---|---|---|
| GET | `/alerts/` | Get all AI optimization alerts |
| GET | `/alerts/{resource_id}` | Get alerts for a specific server |

---

## 🔄 How It Works

1. Register and login via `/auth/register` and `/auth/login`
2. Register a cloud server via `POST /servers/`
3. API saves the server to PostgreSQL
4. API drops an analysis task into Redis via Celery
5. API returns response immediately ✅
6. Celery Worker picks up the task from Redis
7. If Azure resource → fetches real CPU from Azure Monitor
8. Sends data to Gemini AI → gets cost optimization recommendation
9. Saves the alert to PostgreSQL
10. Fetch recommendations via `GET /alerts/`

---

## ⏰ Scheduled Tasks

Every **1 hour** automatically:
- Celery scans ALL registered servers
- Queues fresh AI analysis for each one
- New recommendations saved to database

No manual trigger needed.

---

## 🧪 Running Tests
```bash
pytest tests/ -v
```

Expected output:

tests/test_main.py::test_create_user_success          PASSED ✅
tests/test_main.py::test_create_user_duplicate_email  PASSED ✅
tests/test_main.py::test_get_users                    PASSED ✅
tests/test_main.py::test_create_server_success        PASSED ✅
tests/test_main.py::test_create_server_duplicate      PASSED ✅
tests/test_main.py::test_create_server_invalid_owner  PASSED ✅
tests/test_main.py::test_get_servers                  PASSED ✅
tests/test_main.py::test_get_alerts                   PASSED ✅
tests/test_main.py::test_get_alerts_for_invalid       PASSED ✅


---

## 📁 Project Structure

cloud-optimizer-backend/
├── main.py          # FastAPI routes + error handling
├── models.py        # Database table definitions
├── schemas.py       # Pydantic validation schemas
├── database.py      # Database connection setup
├── Worker.py        # Celery tasks + Gemini AI + Azure Monitor
├── tasks.py         # Scheduled periodic tasks
├── auth.py          # JWT authentication
├── requirements.txt # All dependencies
├── .env             # Environment variables (never commit this)
└── tests/
└── test_main.py # Automated API tests

---

## 🔑 Getting API Keys

- **Gemini API Key** → [Google AI Studio](https://aistudio.google.com)
- **Azure Credentials** → [Azure Portal](https://portal.azure.com)

---

## 👤 Author

Harsith Reddy Majjigapu