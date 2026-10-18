from fastapi import FastAPI, Request, HTTPException, status
import uvicorn
import json
import logging
import os
from typing import Optional, Dict, List, Tuple
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 2026-10-16: LetmeQC DA GOP vao web QC ("tood qc 2d/cvat_2d/web_qc", file rule_tier.py) va TAT o day.
# Ly do: 2 server cung nhan webhook CVAT, cung cong 8000, cung tao Issue -> 1 job bi review 2 lan, Issue trung.
# Muon bat lai (vd de so sanh): dat bien moi truong LETMEQC_ENABLE=1.
if os.getenv("LETMEQC_ENABLE") != "1":
    sys.exit("LetmeQC (app.py) da tat: luat da gop vao web QC. Chay 'tood qc 2d/cvat_2d/web_qc.bat'. "
             "Can bat lai thi dat LETMEQC_ENABLE=1.")

import requests
from src.parser import parse_cvat_api_json
from src.rules import QCRulesEngine
from src.models import Frame
from src.config import cvat_config, qc_config
from src.reports import QCReport

# Load environment variables
from dotenv import load_dotenv
load_dotenv()


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration from environment variables
CVAT_API_URL = os.getenv("CVAT_API_URL", "https://app.cvat.ai/api")
CVAT_TOKEN = os.getenv("CVAT_TOKEN", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", None)
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
UPDATE_JOB_STATUS_ERROR = "Failed to update job status for job %s"

app = FastAPI(
    title="LetmeQC - CVAT Webhook Server",
    description="Webhook endpoint for CVAT to trigger automatic Quality Control checks",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)


class CVATAPI:
    """Helper class for CVAT API interactions with X-Organization header support"""
    
    JOBS_PATH = "/jobs/"
    
    def __init__(self, base_url: str, token: str, org_slug: str = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.org_slug = org_slug
        self.timeout = 30
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers with Authorization and X-Organization if configured"""
        headers = {
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json"
        }
        if self.org_slug:
            headers["X-Organization"] = self.org_slug
        return headers
    
    def get_job_annotations(self, job_id: int) -> Dict:
        """Fetch annotations for a job"""
        url = self.base_url + self.JOBS_PATH + str(job_id) + "/annotations"
        logger.info("Fetching annotations from: %s", url)
        
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException:
            logger.exception("Failed to fetch annotations for job %s", job_id)
            raise
    
    def create_issue(self, job_id: int, frame: int, position: List[float],
                     message: str, assignee_id: Optional[int] = None) -> Dict:
        """Create a QC issue in CVAT with position [x1, y1, x2, y2]"""
        url = self.base_url + "/issues"
        issue_data = {
            "frame": int(frame),
            "position": position,
            "job": job_id,
            "message": message,
            "resolved": False
        }
        
        if assignee_id:
            issue_data["assignee"] = assignee_id
        
        logger.info("Creating issue for job %s, frame %s: %s", job_id, frame, message)
        
        try:
            response = requests.post(url, json=issue_data,
                                    headers=self._get_headers(), timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            response_text = e.response.text if hasattr(e, 'response') else ''
            logger.exception("Failed to create issue. CVAT Response: %s", response_text)
            raise
    
    def update_job_status(self, job_id: int, stage: str, state: str,
                          assignee_id: Optional[int] = None) -> Dict:
        """Update job status via PATCH"""
        url = self.base_url + self.JOBS_PATH + str(job_id)
        payload = {"stage": stage, "state": state}
        
        if assignee_id:
            payload["assignee"] = assignee_id
        
        try:
            response = requests.patch(url, json=payload,
                                     headers=self._get_headers(), timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException:
            logger.exception(UPDATE_JOB_STATUS_ERROR, job_id)
            raise
    
    def get_job_info(self, job_id: int) -> Dict:
        """Get job information"""
        url = self.base_url + self.JOBS_PATH + str(job_id)
        
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException:
            logger.exception("Failed to get job info for job %s", job_id)
            raise

    def get_job_labels(self, job_id: int) -> Dict[int, str]:
        """Fetch labels metadata for mapping ID to Name"""
        url = self.base_url + "/labels?job_id=" + str(job_id)
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=self.timeout)
            response.raise_for_status()
            results = response.json().get("results", [])
            return {item["id"]: item["name"] for item in results}
        except Exception:
            logger.exception("Failed to fetch labels for job %s", job_id)
            return {}


# Initialize CVAT API client
cvat_api = None
if CVAT_TOKEN:
    cvat_api = CVATAPI(CVAT_API_URL, CVAT_TOKEN, cvat_config.org_slug)
    logger.info("CVAT API client initialized")
else:
    logger.warning("CVAT_TOKEN not set - API calls will fail")


def _validate_request(request: Request, payload: Dict) -> Tuple[bool, str, Dict]:
    """Validate webhook request. Returns (is_valid, event, error_response)"""
    if WEBHOOK_SECRET:
        secret = request.headers.get("X-CVAT-Webhook-Secret")
        if secret and secret != WEBHOOK_SECRET:
            logger.error("Invalid webhook secret")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook secret",
                headers={"WWW-Authenticate": "Bearer"}
            )
        elif not secret:
            logger.warning("WEBHOOK_SECRET is set but no secret header provided")
    
    event = payload.get("event", "")
    return True, event, {}


def _handle_ping() -> Dict:
    """Handle ping event"""
    logger.info("Connection successful! Received Ping from CVAT.")
    return {"message": "Ping received"}


def _handle_skip_event(event: str) -> Dict:
    """Handle non-job events"""
    logger.info("Skipping event: %s", event)
    return {"message": "Skipped event: " + event, "status": "skipped"}


def _handle_non_validation(job_id: int, job_status: str) -> Dict:
    """Handle non-validation status"""
    logger.info("Status is '%s' - no QC action required", job_status)
    return {
        "message": "Job " + str(job_id) + " status update received",
        "job_id": job_id,
        "status": job_status,
        "action": "none"
    }


def _fetch_data(job_id: int) -> Tuple[Optional[Dict], Optional[Dict], Optional[List[Frame]], Dict]:
    """Fetch job info, annotations, labels. Returns (job_info, raw_data, frames, error)"""
    try:
        logger.info("Getting job info for job %s", job_id)
        job_info = cvat_api.get_job_info(job_id)
        logger.info("Job Info received")
    except Exception as e:
        logger.exception("Failed to get job info for job %s", job_id)
        return None, None, None, {
            "message": "Failed to get job info: " + str(e),
            "job_id": job_id,
            "status": "error",
            "action": "failed"
        }
    
    try:
        logger.info("Fetching annotations for job %s", job_id)
        raw_data = cvat_api.get_job_annotations(job_id)
        
        if not raw_data or not isinstance(raw_data, dict):
            logger.warning("No annotations found for job %s", job_id)
            return None, None, None, {
                "message": "No annotations found",
                "job_id": job_id,
                "status": "no_annotations",
                "action": "skipped"
            }
        
        logger.info("Received %s shapes", len(raw_data.get('shapes', [])))
        
    except Exception as e:
        logger.exception("Failed to fetch annotations for job %s", job_id)
        return None, None, None, {
            "message": "Failed to fetch annotations: " + str(e),
            "job_id": job_id,
            "status": "error",
            "action": "failed"
        }
    
    try:
        logger.info("Fetching label mapping for job %s", job_id)
        labels_mapping = cvat_api.get_job_labels(job_id)
        logger.info("Parsing CVAT API JSON Data...")
        frames = parse_cvat_api_json(raw_data, labels_mapping)
        logger.info("Successfully parsed %s frames", len(frames))
        return job_info, raw_data, frames, None
        
    except Exception as e:
        logger.exception("Failed to parse CVAT JSON for job %s", job_id)
        return None, None, None, {
            "message": "Failed to parse annotations: " + str(e),
            "job_id": job_id,
            "status": "parse_error",
            "action": "failed"
        }


def _run_qc(frames: List[Frame]) -> List[Dict]:
    """Run QC checks on frames"""
    try:
        logger.info("Running QC checks...")
        qc_engine = QCRulesEngine(
            min_box_area=qc_config.min_box_area,
            iou_threshold=qc_config.iou_threshold,
            duplicate_iou_threshold=qc_config.duplicate_iou_threshold,
            min_polygon_points=qc_config.min_polygon_points,
            max_aspect_ratio=qc_config.max_aspect_ratio,
            min_aspect_ratio=qc_config.min_aspect_ratio,
            mask_tolerance=qc_config.mask_tolerance,
            bbox_tolerance=qc_config.bbox_tolerance
        )
        errors = qc_engine.run_qc_check(frames)
        logger.info("QC Result: %s errors found", len(errors))
        return errors
        
    except Exception:
        logger.exception("QC check failed")
        raise


def _process_failure(job_id: int, job_name: str, errors: List[Dict],
                      assignee_id: Optional[int], raw_data: Dict, frames: List[Frame],
                      job_info: Optional[Dict] = None) -> Dict:
    """Process QC failure - create issues and update job status"""
    logger.warning("QC FAILED: %s errors found", len(errors))
    
    report = QCReport(job_id=job_id, job_name=job_name)
    
    # Add job information from API
    if job_info:
        report.project_id = job_info.get('project', {}).get('id')
        report.project_name = job_info.get('project', {}).get('name')
        report.assignee_id = assignee_id
        report.assignee_name = job_info.get('assignee', {}).get('username') if job_info.get('assignee') else None
        report.job_created_date = job_info.get('created')
        report.job_updated_date = job_info.get('updated')
        report.job_stage = job_info.get('stage')
        report.job_state = job_info.get('state')
    
    # Add annotation statistics from raw_data
    if raw_data:
        meta = raw_data.get('meta', {})
        size = meta.get('size', {})
        report.image_width = size.get('width')
        report.image_height = size.get('height')
        report.total_shapes = len(raw_data.get('shapes', []))
        report.total_tracks = len(raw_data.get('tracks', []))
        report.total_tags = len(raw_data.get('tags', []))
        report.frame_count = len(meta.get('frames', []))
    
    report.total_frames = len(frames)
    report.total_annotations = len(raw_data.get('shapes', [])) + len(raw_data.get('tracks', []))
    
    for error in errors:
        report.add_error(error.get("Error_Type", "UNKNOWN"), error.get("Message", ""))
    report.status = "failed"
    
    created_issues = []
    for error in errors:
        position = error.get("Position", [0, 0, 0, 0])
        message = error.get("Message", "Unknown error")
        frame_name = error.get("Frame", "0")
        
        try:
            issue = cvat_api.create_issue(
                job_id=job_id,
                frame=int(frame_name),
                position=position,
                message=message,
                assignee_id=assignee_id
            )
            created_issues.append(issue)
            report.issues_created += 1
            logger.info("Created issue for frame %s", frame_name)
        except Exception:
            report.failed_issue_creations += 1
            logger.exception("Failed to create issue for frame %s", frame_name)
    
    try:
        cvat_api.update_job_status(
            job_id=job_id,
            stage="annotation",
            state="rejected",
            assignee_id=assignee_id
        )
        report.job_status_updated = "rejected"
        logger.info("Job %s status updated to rejected", job_id)
    except Exception:
        logger.exception(UPDATE_JOB_STATUS_ERROR, job_id)
    
    report_path = report.save()
    
    return {
        "message": "QC failed - " + str(len(errors)) + " errors found",
        "job_id": job_id,
        "total_errors": len(errors),
        "error_types": report.get_error_type_counts(),
        "created_issues": len(created_issues),
        "action": "rejected",
        "report_path": report_path,
        "timestamp": datetime.now().isoformat()
    }


def _process_success(job_id: int, job_name: str, frames: List[Frame],
                        assignee_id: Optional[int], raw_data: Dict, job_info: Optional[Dict] = None) -> Dict:
    """Process QC success - update job status"""
    logger.info("QC PASSED: No errors found in job %s", job_id)
    
    report = QCReport(job_id=job_id, job_name=job_name)
    
    # Add job information from API
    if job_info:
        report.project_id = job_info.get('project', {}).get('id')
        report.project_name = job_info.get('project', {}).get('name')
        report.assignee_id = assignee_id
        report.assignee_name = job_info.get('assignee', {}).get('username') if job_info.get('assignee') else None
        report.job_created_date = job_info.get('created')
        report.job_updated_date = job_info.get('updated')
        report.job_stage = job_info.get('stage')
        report.job_state = job_info.get('state')
    
    # Add annotation statistics from raw_data
    if raw_data:
        meta = raw_data.get('meta', {})
        size = meta.get('size', {})
        report.image_width = size.get('width')
        report.image_height = size.get('height')
        report.total_shapes = len(raw_data.get('shapes', []))
        report.total_tracks = len(raw_data.get('tracks', []))
        report.total_tags = len(raw_data.get('tags', []))
        report.frame_count = len(meta.get('frames', []))
    
    report.total_frames = len(frames)
    report.total_annotations = len(raw_data.get('shapes', [])) + len(raw_data.get('tracks', []))
    report.status = "passed"
    
    try:
        cvat_api.update_job_status(
            job_id=job_id,
            stage="validation",
            state="",
            assignee_id=assignee_id
        )
        report.job_status_updated = "validation"
        logger.info("Job %s status confirmed as validation", job_id)
    except Exception:
        logger.exception(UPDATE_JOB_STATUS_ERROR, job_id)
    
    report_path = report.save()
    
    total_bboxes = sum(len(f.bboxes) for f in frames)
    total_polygons = sum(len(f.polygons) for f in frames)
    
    return {
        "message": "QC passed - No errors found",
        "job_id": job_id,
        "job_name": job_name,
        "frames_checked": len(frames),
        "total_bboxes": total_bboxes,
        "total_polygons": total_polygons,
        "action": "passed",
        "report_path": report_path,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/webhook/cvat",
         responses={
             200: {"description": "Webhook processed successfully"},
             400: {"description": "Invalid JSON payload"},
             401: {"description": "Invalid webhook secret"},
             500: {"description": "Internal server error"}
         })
async def cvat_webhook(request: Request):
    """CVAT Webhook Endpoint"""
    try:
        payload = await request.json()
        logger.info("Received webhook payload")
        
        is_valid, event, error_response = _validate_request(request, payload)
        if not is_valid:
            return error_response
        
        if event == "ping":
            return _handle_ping()
        
        if event != "update:job":
            return _handle_skip_event(event)
        
        job = payload.get("job", {})
        job_id = job.get("id")
        job_name = job.get("name", "unknown")
        job_status = job.get("status")
        assignee = job.get("assignee") or {}
        assignee_id = assignee.get("id")
        
        logger.info("Job Update: ID=%s | Name='%s' | Status='%s'",
                   job_id, job_name, job_status)
        
        if job_status != "validation":
            return _handle_non_validation(job_id, job_status)
        
        logger.info("Starting automatic QC process for job %s", job_id)
        
        if not cvat_api:
            logger.error("CVAT API not configured - cannot fetch annotations")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="CVAT API not configured. Please set CVAT_TOKEN environment variable."
            )
        
        job_info, raw_data, frames, fetch_error = _fetch_data(job_id)
        
        if fetch_error:
            return fetch_error
        
        errors = _run_qc(frames)
        
        if errors:
            return _process_failure(job_id, job_name, errors, assignee_id, raw_data, frames, job_info)
        else:
            return _process_success(job_id, job_name, frames, assignee_id, raw_data, job_info)
            
    except json.JSONDecodeError:
        logger.exception("Invalid JSON payload")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error processing webhook")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@app.get("/")
async def root():
    """Health check and service info"""
    return {
        "status": "running",
        "service": "LetmeQC CVAT Webhook Server",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "webhook_endpoint": "/webhook/cvat"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "cvat_api_configured": CVAT_TOKEN is not None and CVAT_TOKEN != "",
        "qc_engine_ready": True
    }


@app.get("/config")
async def get_config():
    """Get current configuration"""
    return {
        "cvat_api_url": CVAT_API_URL,
        "cvat_token_set": CVAT_TOKEN is not None and CVAT_TOKEN != "",
        "cvat_org_slug": cvat_config.org_slug,
        "min_box_area": qc_config.min_box_area,
        "iou_threshold": qc_config.iou_threshold,
        "webhook_secret_set": WEBHOOK_SECRET is not None
    }


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  LetmeQC - CVAT Webhook Server")
    logger.info("=" * 60)
    logger.info("  Server: http://%s:%s", SERVER_HOST, SERVER_PORT)
    logger.info("  Webhook: POST http://%s:%s/webhook/cvat", SERVER_HOST, SERVER_PORT)
    logger.info("  Health: GET http://%s:%s/health", SERVER_HOST, SERVER_PORT)
    logger.info("  Docs: http://%s:%s/docs", SERVER_HOST, SERVER_PORT)
    logger.info("  Config: GET http://%s:%s/config", SERVER_HOST, SERVER_PORT)
    logger.info("=" * 60)
    
    if not CVAT_TOKEN:
        logger.warning("WARNING: CVAT_TOKEN not set - API calls will fail!")
        logger.warning("   Set CVAT_TOKEN environment variable or in .env file")
    
    if not WEBHOOK_SECRET:
        logger.warning("WARNING: WEBHOOK_SECRET not set - anyone can trigger webhook!")
    
    if not cvat_config.org_slug:
        logger.warning("WARNING: CVAT_ORG_SLUG not set - organization header will not be sent!")
    
    uvicorn.run(
        "app:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        log_level="info",
        reload=True
    )
