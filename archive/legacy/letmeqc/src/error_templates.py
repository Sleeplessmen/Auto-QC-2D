"""Error message template system for QC rules"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class ErrorTemplate:
    """Template for error messages with severity and suggestion"""
    severity: str
    message: str
    suggestion: str


ERROR_TEMPLATES: Dict[str, ErrorTemplate] = {
    "Bbox_Out_Of_Bounds": ErrorTemplate(
        severity="high",
        message="Box vượt ngoài viền ảnh ({img_w}x{img_h}). Tọa độ xbr/ybr vượt quá giới hạn.",
        suggestion="Kéo viền box thu gọn vào bên trong viền ảnh."
    ),
    "Bbox_Too_Small": ErrorTemplate(
        severity="high",
        message="Diện tích box ({area:.1f}px) nhỏ hơn mức cho phép ({min_area}px).",
        suggestion="Hãy phóng to khu vực này. Nếu là object thật, vẽ sát viền; nếu là rác, hãy xóa."
    ),
    "Polygon_Point_Count": ErrorTemplate(
        severity="high",
        message="Polygon chỉ có {point_count} điểm, cần ≥ {min_points} điểm.",
        suggestion="Thêm ít nhất 1 điểm nữa."
    ),
    "Bbox_Overlap": ErrorTemplate(
        severity="medium",
        message="Phát hiện {count} box '{label}' (ID {obj_ids}) trùng lắp {iou:.0%} IoU.",
        suggestion="Gộp các box trùng lắp hoặc chia tách nếu là các object riêng biệt."
    ),
    "Polygon_Self_Intersect": ErrorTemplate(
        severity="high",
        message="Polygon của class '{label}' bị tự cắt chéo nét.",
        suggestion="Xóa điểm vắt chéo hoặc dùng công cụ Split/Edit polygon."
    ),
    "Duplicate_Objects": ErrorTemplate(
        severity="high",
        message="Duplicate Object: Trùng lặp hoàn toàn với ID {obj_ids}.",
        suggestion="Xóa bớt các bản sao trùng lặp."
    ),
    "Mask_Out_Of_Box": ErrorTemplate(
        severity="medium",
        message="Mask '{label}' bị lem ra ngoài Bbox > {tolerance}px.",
        suggestion="Điều chỉnh Polygon/Mask cho khớp với Bounding Box."
    ),
    "Extreme_Aspect_Ratio": ErrorTemplate(
        severity="low",
        message="Aspect ratio bất thường (Ratio = {ratio:.1f}).",
        suggestion="Kiểm tra lại object. Nếu là lỗi, điều chỉnh kích thước."
    ),
    "Label_Consistency": ErrorTemplate(
        severity="medium",
        message="Class '{child_label}' nằm trong Class '{parent_label}' - không phù hợp.",
        suggestion="Kiểm tra lại nhãn."
    ),
    "Missing_Required_Attributes": ErrorTemplate(
        severity="medium",
        message="'{label}' thiếu thuộc tính bắt buộc '{missing_attribute}' (bắt buộc: {required_attributes}).",
        suggestion="Chọn giá trị cho thuộc tính còn thiếu theo Guidelines."
    ),
    "UNKNOWN": ErrorTemplate(
        severity="medium",
        message="Phát hiện lỗi không xác định.",
        suggestion="Kiểm tra lại nhãn theo Guidelines."
    )
}


def format_error_message(template_key: str, **kwargs) -> str:
    """
    Format an error message using the specified template.
    
    Args:
        template_key: Key of the error template
        **kwargs: Keyword arguments to format the message
    
    Returns:
        str: Formatted error message
    """
    template = ERROR_TEMPLATES.get(template_key, ERROR_TEMPLATES["UNKNOWN"])
    try:
        return template.message.format(**kwargs)
    except KeyError:
        return template.message


def get_error_template(template_key: str) -> ErrorTemplate:
    """
    Get error template by key.
    
    Args:
        template_key: Key of the error template
    
    Returns:
        ErrorTemplate: The template object
    """
    return ERROR_TEMPLATES.get(template_key, ERROR_TEMPLATES["UNKNOWN"])


def generate_error_payload(frame_name: str, obj_id: Any, error_type: str,
                           position: Optional[List[float]] = None, **extra_info) -> Dict[str, Any]:
    """
    Generate a complete error payload with all required fields.
    
    Args:
        frame_name: Name/ID of the frame
        obj_id: ID of the object
        error_type: Type of error (must match a template key)
        position: [x1, y1, x2, y2] coordinates of the error position
        **extra_info: Additional information for message formatting
    
    Returns:
        Dict: Complete error payload with Severity, Suggestion, Details
    """
    template = get_error_template(error_type)
    
    payload = {
        "Frame": str(frame_name),
        "Object_ID": str(obj_id),
        "Error_Type": error_type,
        "Message": format_error_message(error_type, **extra_info),
        "Severity": template.severity,
        "Suggestion": template.suggestion,
        "Details": {}
    }
    
    if position is not None:
        payload["Position"] = position
    
    if extra_info:
        payload["Details"].update(extra_info)
    
    return payload
