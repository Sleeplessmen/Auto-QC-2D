# LetmeQC - TODO List for Production & Beta Testing

## 📋 Overview
This document outlines tasks for refactoring the codebase into smaller modules, preparing for production deployment, and setting up CI/CD with GitHub Actions.

---

## 🎯 Priority 1: Code Refactoring (Day 1 - Morning)

### Goal: Split monolithic `app.py` into modular components

#### 1.1 Extract CVATAPI Client Module
- **File**: `src/clients/cvat_client.py`
- **Status**: ⬜ Not Started
- **Description**: Move `CVATAPI` class from `app.py` to separate module
- **Tasks**:
  - [ ] Create `src/clients/__init__.py`
  - [ ] Move `CVATAPI` class to `src/clients/cvat_client.py`
  - [ ] Update imports in `app.py`
  - [ ] Add proper error handling and retries
  - [ ] Add type hints for all methods

#### 1.2 Extract Webhook Handlers Module
- **File**: `src/handlers/webhook_handlers.py`
- **Status**: ⬜ Not Started
- **Description**: Move webhook-related functions to separate handlers
- **Tasks**:
  - [ ] Create `src/handlers/__init__.py`
  - [ ] Move `_validate_request`, `_handle_ping`, `_handle_skip_event`, `_handle_non_validation`
  - [ ] Update imports in `app.py`
  - [ ] Keep FastAPI route decorators in `app.py`

#### 1.3 Extract QC Processing Service
- **File**: `src/services/qc_service.py`
- **Status**: ⬜ Not Started
- **Description**: Move QC processing logic to service layer
- **Tasks**:
  - [ ] Create `src/services/__init__.py`
  - [ ] Move `_fetch_data`, `_run_qc`, `_process_failure`, `_process_success`
  - [ ] Create `QCService` class to encapsulate processing logic
  - [ ] Add proper dependency injection for CVATAPI and config
  - [ ] Update imports in `app.py`

#### 1.4 Create Main App Module
- **File**: `src/app/main.py`
- **Status**: ⬜ Not Started
- **Description**: Move FastAPI app initialization and routes
- **Tasks**:
  - [ ] Move FastAPI app creation to `src/app/main.py`
  - [ ] Move route handlers (`cvat_webhook`, `root`, `health_check`, `get_config`)
  - [ ] Keep `app.py` as entry point for uvicorn
  - [ ] Ensure proper module structure

---

## 🎯 Priority 2: Production Readiness (Day 1 - Afternoon)

### 2.1 Environment & Dependencies
- **Status**: ⬜ Not Started
- **Tasks**:
  - [ ] Create `requirements.txt` with pinned versions
  - [ ] Create `requirements-dev.txt` for development dependencies
  - [ ] Add `pyproject.toml` or setup `poetry` for dependency management
  - [ ] Document all required environment variables in `.env.example`

### 2.2 Configuration Management
- **File**: `src/config.py` (enhance)
- **Status**: ⬜ Not Started
- **Tasks**:
  - [ ] Add validation for environment variables
  - [ ] Create `Settings` class using Pydantic Settings Management
  - [ ] Support multiple configuration sources (env, file, CLI)
  - [ ] Add default values and validation rules

### 2.3 Logging Configuration
- **File**: `src/config/logging_config.py`
- **Status**: ⬜ Not Started
- **Tasks**:
  - [ ] Move logging config to separate module
  - [ ] Support different log levels for different modules
  - [ ] Add file logging with rotation
  - [ ] Support JSON logging for production

### 2.4 Error Handling & Monitoring
- **Status**: ⬜ Not Started
- **Tasks**:
  - [ ] Create custom exception hierarchy
  - [ ] Add structured error responses
  - [ ] Implement request tracing with correlation IDs
  - [ ] Add Prometheus metrics endpoint for monitoring

---

## 🎯 Priority 3: Beta Testing Preparation (Day 2 - Morning)

### 3.1 Documentation
- **Status**: ⬜ Not Started
- **Tasks**:
  - [ ] Create `README.md` with:
    - Project overview
    - Setup instructions
    - Configuration guide
    - Usage examples
    - Troubleshooting
  - [ ] Add API documentation with Swagger/OpenAPI
  - [ ] Create example `.env` files for different environments
  - [ ] Document webhook payload structure

### 3.2 Docker & Containerization
- **File**: `Dockerfile`, `docker-compose.yml`
- **Status**: ⬜ Not Started
- **Tasks**:
  - [ ] Create production Dockerfile
  - [ ] Create development Dockerfile with hot-reload
  - [ ] Create docker-compose.yml with all services
  - [ ] Add `.dockerignore` file
  - [ ] Document build and run instructions

### 3.3 Configuration for Different Environments
- **Status**: ⬜ Not Started
- **Tasks**:
  - [ ] Create config files for dev, staging, production
  - [ ] Implement environment detection
  - [ ] Support CLI overrides for critical settings
  - [ ] Document all configuration options

### 3.4 Testing Setup
- **Status**: ⬜ Not Started
- **Tasks**:
  - [ ] Create `tests/` directory structure
  - [ ] Add pytest configuration
  - [ ] Write unit tests for core modules
  - [ ] Write integration tests for API endpoints
  - [ ] Add mock for CVAT API calls
  - [ ] Setup test coverage reporting

---

## 🎯 Priority 4: GitHub Actions CI/CD (Day 2 - Afternoon)

### 4.1 CI Pipeline
- **File**: `.github/workflows/ci.yml`
- **Status**: ⬜ Not Started
- **Tasks**:
  - [ ] Create workflow for pull requests and main branch
  - [ ] Setup Python environment with caching
  - [ ] Install dependencies
  - [ ] Run linting (flake8, black, isort)
  - [ ] Run type checking (mypy)
  - [ ] Run unit tests
  - [ ] Generate coverage report
  - [ ] Build Docker image (for testing)

### 4.2 CD Pipeline
- **File**: `.github/workflows/cd.yml`
- **Status**: ⬜ Not Started
- **Tasks**:
  - [ ] Create deployment workflow
  - [ ] Setup deployment triggers (tags, releases)
  - [ ] Build production Docker image
  - [ ] Push to Docker registry (Docker Hub, GitHub Container Registry)
  - [ ] Deploy to staging environment
  - [ ] Manual approval for production deployment

### 4.3 Additional Workflows
- **Status**: ⬜ Not Started
- **Tasks**:
  - [ ] Security scanning (Snyk, Trivy)
  - [ ] Code quality checks (SonarCloud)
  - [ ] Automated dependency updates
  - [ ] Release automation

---

## 🎯 Priority 5: Beta Testing Rollout

### 5.1 Beta Version
- **Status**: ⬜ Not Started
- **Tasks**:
  - [ ] Create v0.2.0-beta release
  - [ ] Tag the commit
  - [ ] Generate release notes
  - [ ] Create beta tester guide

### 5.2 Beta Tester Setup
- **Status**: ⬜ Not Started
- **Tasks**:
  - [ ] Create quick start guide for beta testers
  - [ ] Setup feedback collection mechanism
  - [ ] Create issue template for bug reports
  - [ ] Setup Discord/Slack channel for beta testers
  - [ ] Prepare sample CVAT webhook payloads for testing

### 5.3 Monitoring & Feedback
- **Status**: ⬜ Not Started
- **Tasks**:
  - [ ] Setup error tracking (Sentry, Rollbar)
  - [ ] Collect usage analytics (opt-in)
  - [ ] Regular check-ins with beta testers
  - [ ] Document common issues and workarounds

---

## 📊 Estimated Timeline

### Day 1 (Refactoring & Production Prep)
- **Morning (4h)**: Code Refactoring (Tasks 1.1-1.4)
- **Afternoon (4h)**: Production Readiness (Tasks 2.1-2.4)

### Day 2 (Beta Prep & CI/CD)
- **Morning (4h)**: Beta Testing Preparation (Tasks 3.1-3.4)
- **Afternoon (4h)**: GitHub Actions Setup (Tasks 4.1-4.3)

### Day 3 (Testing & Documentation)
- **Full Day**: Manual testing, documentation review, beta tester onboarding

---

## 🏆 Success Criteria

### For Refactoring
- [ ] All modules are properly separated
- [ ] No circular dependencies
- [ ] All existing functionality preserved
- [ ] Code is more maintainable and testable

### For Production Readiness
- [ ] Can be deployed with Docker
- [ ] All configurations are externalized
- [ ] Proper error handling and logging
- [ ] Health checks and monitoring in place

### For Beta Testing
- [ ] At least 3 external beta testers
- [ ] Clear documentation for setup and usage
- [ ] Feedback collection mechanism working
- [ ] No critical bugs in core functionality

### For CI/CD
- [ ] All PRs run through CI pipeline
- [ ] Main branch always deployable
- [ ] Automated builds and deployments
- [ ] Security scanning integrated

---

## 📚 References

- FastAPI Documentation: https://fastapi.tiangolo.com/
- GitHub Actions Documentation: https://docs.github.com/en/actions
- Docker Best Practices: https://docs.docker.com/develop/dev-best-practices/
- Python Project Structure: https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/

---

## 🔄 Update History

- 2026-10-14: Initial plan created
