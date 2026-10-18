"""
LetmeQC - A Quality Control Tool for CVAT Format Annotations

This package provides tools for parsing and validating CVAT format annotation files,
particularly for computer vision tasks like object detection and segmentation.
"""

from .models import Bbox, Polygon, Frame, FrameTag
from .parser import parse_cvat_api_json
from .rules import QCRulesEngine
from .config import qc_config, cvat_config
from .utils import calculate_iou, calculate_intersection_box, get_bbox_from_points, clamp_to_image, calculate_aspect_ratio
from .error_templates import generate_error_payload, get_error_template, format_error_message
from .reports import QCReport

__version__ = "0.1.0"
__all__ = [
    "Bbox", "Polygon", "Frame", "FrameTag",
    "parse_cvat_api_json",
    "QCRulesEngine",
    "qc_config", "cvat_config",
    "calculate_iou", "calculate_intersection_box", "get_bbox_from_points", 
    "clamp_to_image", "calculate_aspect_ratio",
    "generate_error_payload", "get_error_template", "format_error_message",
    "QCReport"
]
