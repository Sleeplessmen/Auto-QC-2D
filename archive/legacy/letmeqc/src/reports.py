"""
QC Report - Summary system for QC runs
- Save JSON files
- Keep only max 5 reports (delete oldest)
- Short summary files, max 50 lines
"""
import json
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path


class QCReport:
    """Class for managing QC reports"""
    
    def __init__(self, job_id: int, job_name: str = "unknown"):
        self.job_id = job_id
        self.job_name = job_name
        self.timestamp = datetime.now().isoformat()
        self.status = "pending"
        
        # Job Information (from job_info API)
        self.project_id: Optional[int] = None
        self.project_name: Optional[str] = None
        self.assignee_id: Optional[int] = None
        self.assignee_name: Optional[str] = None
        self.job_created_date: Optional[str] = None
        self.job_updated_date: Optional[str] = None
        self.job_stage: Optional[str] = None
        self.job_state: Optional[str] = None
        
        # Annotation Statistics (from raw_data API)
        self.image_width: Optional[int] = None
        self.image_height: Optional[int] = None
        self.total_shapes: int = 0
        self.total_tracks: int = 0
        self.total_tags: int = 0
        self.frame_count: int = 0
        
        # Frame and annotation counts
        self.total_frames = 0
        self.total_annotations = 0
        self.errors: List[Dict] = []
        self.error_type_counts: Dict[str, int] = {}
        self.issues_created = 0
        self.failed_issue_creations = 0
        self.job_status_updated: Optional[str] = None
    
    def add_error(self, error_type: str, message: str):
        """Add an error to the report"""
        self.errors.append({
            "type": error_type,
            "message": message,
            "timestamp": datetime.now().isoformat()
        })
        self.error_type_counts[error_type] = self.error_type_counts.get(error_type, 0) + 1
    
    def get_error_type_counts(self) -> Dict[str, int]:
        """Get error counts by type"""
        return self.error_type_counts
    
    def to_summary_dict(self) -> Dict:
        """Convert report to summary dictionary with detailed job and annotation info"""
        summary = {
            "job_id": self.job_id,
            "job_name": self.job_name,
            "timestamp": self.timestamp,
            "status": self.status,
            "job_info": {
                "project_id": self.project_id,
                "project_name": self.project_name,
                "assignee_id": self.assignee_id,
                "assignee_name": self.assignee_name,
                "created_date": self.job_created_date,
                "updated_date": self.job_updated_date,
                "stage": self.job_stage,
                "state": self.job_state
            },
            "annotation_statistics": {
                "image_width": self.image_width,
                "image_height": self.image_height,
                "total_shapes": self.total_shapes,
                "total_tracks": self.total_tracks,
                "total_tags": self.total_tags,
                "frame_count": self.frame_count,
                "total_frames": self.total_frames,
                "total_annotations": self.total_annotations
            },
            "qc_results": {
                "total_errors": len(self.errors),
                "error_type_counts": self.error_type_counts,
                "issues_created": self.issues_created,
                "failed_issue_creations": self.failed_issue_creations,
                "job_status_updated": self.job_status_updated
            }
        }
        return summary
    
    def save(self, reports_dir: str = "reports") -> str:
        """Save report to JSON file"""
        Path(reports_dir).mkdir(parents=True, exist_ok=True)
        
        existing_reports = sorted(
            Path(reports_dir).glob("report_job_*.json"),
            key=lambda p: p.stat().st_mtime
        )
        
        while len(existing_reports) >= 5:
            oldest = existing_reports.pop(0)
            oldest.unlink()
        
        filename = f"report_job_{self.job_id}_{self.timestamp.replace(':', '-').replace('.', '-')}.json"
        filepath = Path(reports_dir) / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.to_summary_dict(), f, indent=2, ensure_ascii=False)
        
        return str(filepath)
    
    @staticmethod
    def load(filepath: str) -> Optional['QCReport']:
        """Load report from file with support for new fields and backward compatibility"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            report = QCReport(data["job_id"], data.get("job_name", "unknown"))
            report.timestamp = data["timestamp"]
            report.status = data["status"]
            
            # Load job_info if available (new format)
            job_info = data.get("job_info", {})
            report.project_id = job_info.get("project_id")
            report.project_name = job_info.get("project_name")
            report.assignee_id = job_info.get("assignee_id")
            report.assignee_name = job_info.get("assignee_name")
            report.job_created_date = job_info.get("created_date")
            report.job_updated_date = job_info.get("updated_date")
            report.job_stage = job_info.get("stage")
            report.job_state = job_info.get("state")
            
            # Load annotation_statistics if available (new format)
            ann_stats = data.get("annotation_statistics", {})
            report.image_width = ann_stats.get("image_width")
            report.image_height = ann_stats.get("image_height")
            report.total_shapes = ann_stats.get("total_shapes", 0)
            report.total_tracks = ann_stats.get("total_tracks", 0)
            report.total_tags = ann_stats.get("total_tags", 0)
            report.frame_count = ann_stats.get("frame_count", 0)
            report.total_frames = ann_stats.get("total_frames", 0)
            report.total_annotations = ann_stats.get("total_annotations", 0)
            
            # Load qc_results if available (new format)
            qc_results = data.get("qc_results", {})
            if qc_results:
                report.error_type_counts = qc_results.get("error_type_counts", {})
                report.issues_created = qc_results.get("issues_created", 0)
                report.failed_issue_creations = qc_results.get("failed_issue_creations", 0)
                report.job_status_updated = qc_results.get("job_status_updated")
            else:
                # Fallback to old summary format for backward compatibility
                summary = data.get("summary", {})
                report.total_frames = summary.get("total_frames", report.total_frames)
                report.total_annotations = summary.get("total_annotations", report.total_annotations)
                report.error_type_counts = summary.get("error_type_counts", report.error_type_counts)
                report.issues_created = summary.get("issues_created", report.issues_created)
                report.failed_issue_creations = summary.get("failed_issue_creations", report.failed_issue_creations)
                report.job_status_updated = summary.get("job_status", report.job_status_updated)
            
            return report
        except Exception:
            return None
    
    @staticmethod
    def get_all_reports(reports_dir: str = "reports") -> List['QCReport']:
        """Get all reports from directory"""
        reports = []
        if Path(reports_dir).exists():
            for filepath in sorted(
                Path(reports_dir).glob("report_job_*.json"), 
                key=lambda p: p.stat().st_mtime, 
                reverse=True
            ):
                report = QCReport.load(str(filepath))
                if report:
                    reports.append(report)
        return reports
