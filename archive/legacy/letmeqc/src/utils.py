"""Utility functions for geometry calculations and common operations"""
from typing import List, Tuple, Optional


def calculate_iou(box1: Tuple[float, float, float, float], box2: Tuple[float, float, float, float]) -> float:
    """
    Calculate Intersection over Union (IoU) between two bounding boxes.
    
    Args:
        box1: (x1, y1, x2, y2) - top-left and bottom-right coordinates
        box2: (x1, y1, x2, y2) - top-left and bottom-right coordinates
    
    Returns:
        float: IoU value between 0 and 1
    """
    inter_x1, inter_y1 = max(box1[0], box2[0]), max(box1[1], box2[1])
    inter_x2, inter_y2 = min(box1[2], box2[2]), min(box1[3], box2[3])
    
    if inter_x2 < inter_x1 or inter_y2 < inter_y1:
        return 0.0
    
    intersection_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
    box2_area = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union_area = box1_area + box2_area - intersection_area
    
    return intersection_area / union_area if union_area > 0 else 0.0


def calculate_intersection_box(box1: Tuple[float, float, float, float], 
                              box2: Tuple[float, float, float, float]) -> Optional[Tuple]:
    """
    Calculate coordinates of the intersection region between two bounding boxes.
    
    Args:
        box1: (x1, y1, x2, y2) - top-left and bottom-right coordinates
        box2: (x1, y1, x2, y2) - top-left and bottom-right coordinates
    
    Returns:
        Tuple: (x1, y1, x2, y2) of intersection box, or None if no intersection
    """
    inter_x1, inter_y1 = max(box1[0], box2[0]), max(box1[1], box2[1])
    inter_x2, inter_y2 = min(box1[2], box2[2]), min(box1[3], box2[3])
    
    if inter_x2 < inter_x1 or inter_y2 < inter_y1:
        return None
    
    return (inter_x1, inter_y1, inter_x2, inter_y2)


def get_bbox_from_points(points: List[Tuple[float, float]]) -> Tuple:
    """
    Calculate bounding box from a list of points.
    
    Args:
        points: List of (x, y) coordinate tuples
    
    Returns:
        Tuple: (min_x, min_y, max_x, max_y)
    """
    if not points:
        return (0, 0, 0, 0)
    
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def clamp_to_image(bbox: Tuple, img_width: int, img_height: int) -> Tuple:
    """
    Clamp bounding box coordinates to image dimensions.
    
    Args:
        bbox: (x1, y1, x2, y2) - bounding box coordinates
        img_width: Width of the image
        img_height: Height of the image
    
    Returns:
        Tuple: Clamped bounding box coordinates
    """
    return (
        max(0, min(bbox[0], img_width)),
        max(0, min(bbox[1], img_height)),
        max(0, min(bbox[2], img_width)),
        max(0, min(bbox[3], img_height))
    )


def calculate_aspect_ratio(bbox: Tuple) -> float:
    """
    Calculate aspect ratio (width/height) of a bounding box.
    
    Args:
        bbox: (x1, y1, x2, y2) - bounding box coordinates
    
    Returns:
        float: Aspect ratio (width / height)
    """
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    return width / height if height > 0 else float('inf')
