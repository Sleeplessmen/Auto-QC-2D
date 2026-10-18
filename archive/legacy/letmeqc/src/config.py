"""Central configuration management"""
import os
from dataclasses import dataclass


@dataclass
class QCConfig:
    """Configuration for Quality Control rules"""
    min_box_area: float = 100.0
    min_polygon_points: int = 3
    iou_threshold: float = 0.7
    duplicate_iou_threshold: float = 0.98
    max_aspect_ratio: float = 10.0
    min_aspect_ratio: float = 0.1
    mask_tolerance: float = 2.0
    bbox_tolerance: float = 2.0
    
    @classmethod
    def from_env(cls):
        """Load configuration from environment variables"""
        return cls(
            min_box_area=float(os.getenv('MIN_BOX_AREA', '100')),
            min_polygon_points=int(os.getenv('MIN_POLYGON_POINTS', '3')),
            iou_threshold=float(os.getenv('IOU_THRESHOLD', '0.95')),
            duplicate_iou_threshold=float(os.getenv('DUPLICATE_IOU_THRESHOLD', '0.98')),
            max_aspect_ratio=float(os.getenv('MAX_ASPECT_RATIO', '10.0')),
            min_aspect_ratio=float(os.getenv('MIN_ASPECT_RATIO', '0.1')),
            mask_tolerance=float(os.getenv('MASK_TOLERANCE', '2.0')),
            bbox_tolerance=float(os.getenv('BBOX_TOLERANCE', '2.0')),
        )


@dataclass  
class CVATAPIConfig:
    """Configuration for CVAT API client"""
    base_url: str
    token: str
    org_slug: str
    timeout: int = 30
    
    @classmethod
    def from_env(cls):
        """Load configuration from environment variables"""
        return cls(
            base_url=os.getenv('CVAT_API_URL', 'https://app.cvat.ai/api'),
            token=os.getenv('CVAT_TOKEN', ''),
            org_slug=os.getenv('CVAT_ORG_SLUG', None),
            timeout=int(os.getenv('CVAT_TIMEOUT', '30')),
        )


# Global configuration instances
qc_config = QCConfig.from_env()
cvat_config = CVATAPIConfig.from_env()


def get_headers():
    """
    Get HTTP headers for CVAT API requests
    Includes Authorization and X-Organization if org_slug is configured
    """
    headers = {
        "Authorization": f"Bearer {cvat_config.token}",
        "Content-Type": "application/json"
    }
    if cvat_config.org_slug:
        headers["X-Organization"] = cvat_config.org_slug
    return headers
