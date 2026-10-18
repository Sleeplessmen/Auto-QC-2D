# LetmeQC - Development Guide

## 🏗️ Project Structure (After Refactoring)

```
LetmeQC/
├── src/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py           # FastAPI app initialization and routes
│   │   └── dependencies.py    # FastAPI dependencies
│   │
│   ├── clients/
│   │   ├── __init__.py
│   │   └── cvat_client.py    # CVAT API client
│   │
│   ├── handlers/
│   │   ├── __init__.py
│   │   └── webhook_handlers.py  # Webhook request handlers
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── qc_service.py      # QC processing service
│   │   └── report_service.py  # Report generation service
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py        # Main settings using Pydantic
│   │   └── logging_config.py  # Logging configuration
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── frame.py           # Frame, Bbox, Polygon models
│   │   └── report.py          # Report models
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── parser.py          # CVAT JSON parser
│   │   └── helpers.py         # Utility functions
│   │
│   └── rules/
│       ├── __init__.py
│       └── qc_rules.py        # QC Rules Engine
│
├── tests/
│   ├── __init__.py
│   ├── unit/
│   │   ├── test_cvat_client.py
│   │   ├── test_qc_service.py
│   │   ├── test_parser.py
│   │   └── test_models.py
│   │
│   ├── integration/
│   │   ├── test_webhook.py
│   │   └── test_api.py
│   │
│   └── conftest.py
│
├── .github/
│   └── workflows/
│       ├── ci.yml            # Continuous Integration
│       └── cd.yml            # Continuous Deployment
│
├── docs/
│   ├── setup.md
│   ├── configuration.md
│   ├── usage.md
│   └── api.md
│
├── scripts/
│   ├── startup.sh
│   └── health_check.sh
│
├── .env.example
├── .env.test
├── .gitignore
├── .dockerignore
├── Dockerfile
├── Dockerfile.dev
├── docker-compose.yml
├── docker-compose.dev.yml
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── poetry.lock
├── README.md
└── TODO.md
```

---

## 📦 Module Responsibilities

### `src/clients/cvat_client.py`
Responsible for all CVAT API interactions.

**Functions:**
- `get_job_info(job_id)` - Get job information
- `get_job_annotations(job_id)` - Get job annotations
- `get_job_labels(job_id)` - Get label mappings
- `create_issue(job_id, frame, position, message, assignee_id)` - Create QC issue
- `update_job_status(job_id, stage, state, assignee_id)` - Update job status

### `src/handlers/webhook_handlers.py`
Responsible for processing webhook requests.

**Functions:**
- `validate_request(request, payload)` - Validate webhook secret
- `handle_ping()` - Handle CVAT ping event
- `handle_skip_event(event)` - Handle unsupported events
- `handle_non_validation(job_id, job_status)` - Handle non-validation status

### `src/services/qc_service.py`
Responsible for QC processing logic.

**Classes:**
- `QCService` - Main service class

**Methods:**
- `fetch_data(job_id)` - Fetch job data from CVAT
- `run_qc(frames)` - Run QC checks on frames
- `process_failure(job_id, job_name, errors, ...)` - Process failed QC
- `process_success(job_id, job_name, frames, ...)` - Process passed QC

### `src/config/settings.py`
Responsible for application configuration.

**Classes:**
- `Settings` - Main settings using Pydantic
- `CVATSettings` - CVAT-specific settings
- `QCSettings` - QC-specific settings

---

## 🚀 Quick Start

### Development Setup

```bash
# Clone repository
git clone <repository-url>
cd LetmeQC

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements-dev.txt

# Copy example environment file
cp .env.example .env

# Edit .env with your settings
nano .env  # or use your preferred editor

# Run in development mode
uvicorn app:app --reload
```

### Docker Development

```bash
# Build and run with Docker Compose
docker-compose -f docker-compose.dev.yml up --build

# View logs
docker-compose -f docker-compose.dev.yml logs -f

# Stop containers
docker-compose -f docker-compose.dev.yml down
```

### Production Deployment

```bash
# Build production image
docker build -t letmeqc:latest -f Dockerfile .

# Run with environment variables
docker run -d \
  --name letmeqc \
  -p 8000:8000 \
  -e CVAT_TOKEN=your_token \
  -e CVAT_API_URL=https://app.cvat.ai/api \
  -e WEBHOOK_SECRET=your_secret \
  letmeqc:latest
```

---

## 🔧 Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CVAT_TOKEN` | Yes | - | CVAT API authentication token |
| `CVAT_API_URL` | No | `https://app.cvat.ai/api` | CVAT API base URL |
| `CVAT_ORG_SLUG` | No | - | CVAT organization slug for X-Organization header |
| `WEBHOOK_SECRET` | No | - | Secret for validating webhook requests |
| `SERVER_HOST` | No | `0.0.0.0` | Server host to bind |
| `SERVER_PORT` | No | `8000` | Server port to bind |
| `MIN_BOX_AREA` | No | `100` | Minimum bounding box area |
| `IOU_THRESHOLD` | No | `0.95` | IOU threshold for overlap detection |
| `DUPLICATE_IOU_THRESHOLD` | No | `0.98` | IOU threshold for duplicate detection |
| `MIN_POLYGON_POINTS` | No | `3` | Minimum number of polygon points |
| `MAX_ASPECT_RATIO` | No | `10.0` | Maximum aspect ratio for boxes |
| `MIN_ASPECT_RATIO` | No | `0.1` | Minimum aspect ratio for boxes |
| `MASK_TOLERANCE` | No | `2.0` | Mask tolerance for validation |
| `BBOX_TOLERANCE` | No | `2.0` | Bounding box tolerance |

---

## 🧪 Testing

### Run Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/unit/test_cvat_client.py

# Run with verbose output
pytest -v

# Run only integration tests
pytest tests/integration/
```

### Test Data

Sample webhook payloads are available in `tests/fixtures/`.

---

## 📝 API Documentation

The API is automatically documented using Swagger UI:

- **Swagger UI**: `/docs`
- **ReDoc**: `/redoc`

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/webhook/cvat` | CVAT webhook endpoint |
| GET | `/` | Health check and service info |
| GET | `/health` | Health check endpoint |
| GET | `/config` | Get current configuration |

---

## 🐳 Docker

### Production Dockerfile

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Development Dockerfile

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

---

## 📊 Monitoring

### Health Checks

- **Endpoint**: `GET /health`
- **Response**: JSON with status, timestamp, and configuration status

### Metrics (Planned)

- Request count by endpoint
- Error count by type
- Processing time for QC checks
- Queue length (if using async processing)

### Logging

- All requests are logged with correlation IDs
- Errors are logged with full traceback
- Structured JSON logging available for production

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Pull Request Guidelines

- All PRs must pass CI checks
- Include tests for new functionality
- Update documentation as needed
- Keep commits atomic and well-described

---

## 📞 Support

For issues and questions:

- Create an issue in the GitHub repository
- Join the Discord/Slack channel (if available)
- Check the documentation in the `docs/` directory
