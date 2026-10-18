"""QC Rules Engine - Implement tất cả rules Phase 1-3"""
from .models import Frame, Bbox, Polygon
from .error_templates import generate_error_payload
from .utils import calculate_iou, calculate_intersection_box, get_bbox_from_points, clamp_to_image, calculate_aspect_ratio
from typing import List, Dict, Any, Tuple, Optional
from shapely.geometry import Polygon as ShapelyPoly


class QCRulesEngine:
    """QC Rules Engine with comprehensive checks for Phase 1-3"""
    
    def __init__(self, min_box_area=100.0, iou_threshold=0.95,
                 duplicate_iou_threshold=0.98, min_polygon_points=3,
                 max_aspect_ratio=10.0, min_aspect_ratio=0.1,
                 mask_tolerance=2.0, bbox_tolerance=2.0):
        self.min_box_area = min_box_area
        self.iou_threshold = iou_threshold
        self.duplicate_iou_threshold = duplicate_iou_threshold
        self.min_polygon_points = min_polygon_points
        self.max_aspect_ratio = max_aspect_ratio
        self.min_aspect_ratio = min_aspect_ratio
        self.mask_tolerance = mask_tolerance
        self.bbox_tolerance = bbox_tolerance
        
        # Required attributes per label (from label.json)
        # Format: {label_name: [list_of_required_attribute_names]}
        self.required_attributes = {
            "car": ["occluded", "is_parked"],
            "pedestrian": ["action"],
            "image_info": ["weather"]
        }

    def run_qc_check(self, frames: List[Frame]) -> List[Dict[str, Any]]:
        """Run QC checks on all frames and return list of errors"""
        all_errors = []
        for frame in frames:
            errors = self._check_single_frame(frame)
            if errors:
                all_errors.extend(errors)
        return all_errors

    def _check_single_frame(self, frame: Frame) -> List[Dict[str, Any]]:
        """Check a single frame with all Phase 1-3 rules"""
        errors = []
        
        # Phase 1: Critical checks
        errors.extend(self._check_bbox_out_of_bounds(frame))
        errors.extend(self._check_bbox_too_small(frame))
        errors.extend(self._check_polygon_point_count(frame))
        
        # Phase 2: Geometry & Logic checks
        errors.extend(self._check_overlapping_bboxes(frame))
        errors.extend(self._check_self_intersecting_polygons(frame))
        errors.extend(self._check_duplicate_objects(frame))
        errors.extend(self._check_missing_attributes(frame))  # Rule 7 - NEW
        
        # Phase 3: Advanced checks
        errors.extend(self._check_mask_out_of_bbox(frame))
        errors.extend(self._check_extreme_aspect_ratio(frame))
        errors.extend(self._check_label_consistency(frame))
        
        return errors

    # ==================== PHASE 1: CRITICAL CHECKS ====================
    
    def _check_bbox_out_of_bounds(self, frame: Frame) -> List[Dict]:
        """Check if bounding boxes are outside frame boundaries"""
        errors = []
        for box in frame.bboxes:
            is_out = (
                box.xtl < -self.bbox_tolerance or 
                box.ytl < -self.bbox_tolerance or
                box.xbr > frame.width + self.bbox_tolerance or 
                box.ybr > frame.height + self.bbox_tolerance
            )
            if is_out:
                position = self._clamp_bbox_to_frame(box, frame)
                errors.append(generate_error_payload(
                    frame.name, box.id, "Bbox_Out_Of_Bounds", list(position),
                    img_w=frame.width, img_h=frame.height, label=box.label,
                    bounds=[box.xtl, box.ytl, box.xbr, box.ybr]
                ))
        return errors

    def _clamp_bbox_to_frame(self, box: Bbox, frame: Frame) -> Tuple:
        """Clamp bbox coordinates to frame boundaries"""
        return clamp_to_image(
            (box.xtl, box.ytl, box.xbr, box.ybr),
            frame.width,
            frame.height
        )

    def _check_bbox_too_small(self, frame: Frame) -> List[Dict]:
        """Check if bounding boxes are smaller than minimum allowed area"""
        errors = []
        for box in frame.bboxes:
            area = (box.xbr - box.xtl) * (box.ybr - box.ytl)
            if area < self.min_box_area:
                errors.append(self._create_bbox_error(
                    frame, box, "Bbox_Too_Small",
                    area=area, min_area=self.min_box_area
                ))
        return errors

    def _check_polygon_point_count(self, frame: Frame) -> List[Dict]:
        """Check if polygons have minimum required points"""
        errors = []
        for poly in frame.polygons:
            if len(poly.points) < self.min_polygon_points:
                position = get_bbox_from_points(poly.points)
                errors.append(generate_error_payload(
                    frame.name, poly.id, "Polygon_Point_Count", list(position),
                    point_count=len(poly.points),
                    min_points=self.min_polygon_points,
                    label=poly.label
                ))
        return errors

    # ==================== PHASE 2: GEOMETRY & LOGIC CHECKS ====================

    def _check_overlapping_bboxes(self, frame: Frame) -> List[Dict]:
        """Check for overlapping bounding boxes of the same class"""
        errors = []
        label_groups = self._group_bboxes_by_label(frame)
        
        for label, group in label_groups.items():
            if len(group) < 2:
                continue
            errors.extend(self._check_group_overlaps(frame, label, group))
        
        return errors

    def _group_bboxes_by_label(self, frame: Frame) -> Dict[str, List[Bbox]]:
        """Group bboxes by their label"""
        label_groups = {}
        for box in frame.bboxes:
            label_groups.setdefault(box.label, []).append(box)
        return label_groups

    def _check_group_overlaps(self, frame: Frame, label: str, group: List[Bbox]) -> List[Dict]:
        """Check for overlaps within a group of bboxes with same label"""
        errors = []
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                box1, box2 = group[i], group[j]
                if self._boxes_overlap(box1, box2):
                    position = self._get_overlap_position(box1, box2)
                    errors.append(generate_error_payload(
                        frame.name,
                        self._format_obj_ids(box1.id, box2.id),
                        "Bbox_Overlap",
                        position,
                        count=2,
                        label=label,
                        obj_ids=self._format_obj_ids(box1.id, box2.id),
                        iou=self._calculate_box_iou(box1, box2)
                    ))
        return errors

    def _boxes_overlap(self, box1: Bbox, box2: Bbox) -> bool:
        """Check if two boxes overlap above threshold"""
        return self._calculate_box_iou(box1, box2) > self.iou_threshold

    def _get_overlap_position(self, box1: Bbox, box2: Bbox) -> List[float]:
        """Get position of overlap between two boxes"""
        intersection = calculate_intersection_box(
            (box1.xtl, box1.ytl, box1.xbr, box1.ybr),
            (box2.xtl, box2.ytl, box2.xbr, box2.ybr)
        )
        if intersection:
            return list(intersection)
        return [box2.xtl, box2.ytl, box2.xbr, box2.ybr]

    def _calculate_box_iou(self, box1: Bbox, box2: Bbox) -> float:
        """Calculate IoU between two boxes"""
        return calculate_iou(
            (box1.xtl, box1.ytl, box1.xbr, box1.ybr),
            (box2.xtl, box2.ytl, box2.xbr, box2.ybr)
        )

    def _format_obj_ids(self, id1: Any, id2: Any) -> str:
        """Format object IDs for error message"""
        return f"{id1} & {id2}"

    def _create_bbox_error(self, frame: Frame, box: Bbox, error_type: str, **kwargs) -> Dict:
        """Create error payload for bbox errors"""
        position = [box.xtl, box.ytl, box.xbr, box.ybr]
        kwargs['label'] = box.label
        return generate_error_payload(
            frame.name, box.id, error_type, position, **kwargs
        )

    def _check_self_intersecting_polygons(self, frame: Frame) -> List[Dict]:
        """Check for self-intersecting polygons"""
        errors = []
        for poly in frame.polygons:
            if len(poly.points) < 3:
                continue
            errors.extend(self._check_single_polygon(frame, poly))
        return errors

    def _check_single_polygon(self, frame: Frame, poly: Polygon) -> List[Dict]:
        """Check a single polygon for self-intersection"""
        errors = []
        try:
            shapely_poly = ShapelyPoly(poly.points)
            if not shapely_poly.is_valid:
                position = get_bbox_from_points(poly.points)
                errors.append(generate_error_payload(
                    frame.name, poly.id, "Polygon_Self_Intersect", list(position),
                    label=poly.label
                ))
        except Exception:
            pass
        return errors

    def _check_duplicate_objects(self, frame: Frame) -> List[Dict]:
        """Check for duplicate objects with same label and attributes"""
        errors = []
        label_groups = self._group_bboxes_by_label(frame)
        
        for label, group in label_groups.items():
            if len(group) < 2:
                continue
            errors.extend(self._check_group_duplicates(frame, label, group))
        
        return errors

    def _check_group_duplicates(self, frame: Frame, label: str, group: List[Bbox]) -> List[Dict]:
        """Check for duplicates within a group of bboxes"""
        errors = []
        checked = set()
        
        for i in range(len(group)):
            if i in checked:
                continue
            for j in range(i + 1, len(group)):
                box1, box2 = group[i], group[j]
                if self._are_duplicates(box1, box2):
                    errors.append(generate_error_payload(
                        frame.name,
                        self._format_obj_ids(box1.id, box2.id),
                        "Duplicate_Objects",
                        [box2.xtl, box2.ytl, box2.xbr, box2.ybr],
                        obj_ids=self._format_obj_ids(box1.id, box2.id),
                        label=label,
                        iou=self._calculate_box_iou(box1, box2)
                    ))
                    checked.add(j)
        return errors

    def _are_duplicates(self, box1: Bbox, box2: Bbox) -> bool:
        """Check if two boxes are duplicates"""
        iou = self._calculate_box_iou(box1, box2)
        return iou >= self.duplicate_iou_threshold and box1.attributes == box2.attributes

    def _check_missing_attributes(self, frame: Frame) -> List[Dict]:
        """Check if objects are missing required attributes (Rule 7)"""
        errors = []
        
        # Get required attributes for each label
        required_attrs = self.required_attributes
        
        # Check all bboxes
        for box in frame.bboxes:
            label = box.label
            if label in required_attrs:
                for attr_name in required_attrs[label]:
                    # Check if attribute exists and has non-empty value
                    if attr_name not in box.attributes or not box.attributes[attr_name]:
                        position = [box.xtl, box.ytl, box.xbr, box.ybr]
                        errors.append(generate_error_payload(
                            frame.name, box.id, "Missing_Required_Attributes",
                            position,
                            label=label,
                            missing_attribute=attr_name,
                            required_attributes=", ".join(required_attrs[label])
                        ))
        
        # Check all polygons
        for poly in frame.polygons:
            label = poly.label
            if label in required_attrs:
                for attr_name in required_attrs[label]:
                    if attr_name not in poly.attributes or not poly.attributes[attr_name]:
                        position = list(get_bbox_from_points(poly.points))
                        errors.append(generate_error_payload(
                            frame.name, poly.id, "Missing_Required_Attributes",
                            position,
                            label=label,
                            missing_attribute=attr_name,
                            required_attributes=", ".join(required_attrs[label])
                        ))
        
        return errors

    # ==================== PHASE 3: ADVANCED CHECKS ====================

    def _check_mask_out_of_bbox(self, frame: Frame) -> List[Dict]:
        """Check if polygon mask extends beyond its bounding box"""
        errors = []
        for poly in frame.polygons:
            if len(poly.points) < 3:
                continue
            errors.extend(self._check_single_mask(frame, poly))
        return errors

    def _check_single_mask(self, frame: Frame, poly: Polygon) -> List[Dict]:
        """Check a single polygon mask against its bbox"""
        errors = []
        matching_box = self._find_matching_bbox(frame, poly)
        if not matching_box:
            return errors
        
        try:
            shapely_poly = ShapelyPoly(poly.points)
            min_x, min_y, max_x, max_y = shapely_poly.bounds
            
            if self._is_mask_out_of_bbox(min_x, min_y, max_x, max_y, matching_box):
                errors.append(generate_error_payload(
                    frame.name, poly.id, "Mask_Out_Of_Box",
                    [min_x, min_y, max_x, max_y],
                    label=poly.label,
                    tolerance=self.mask_tolerance
                ))
        except Exception:
            pass
        return errors

    def _find_matching_bbox(self, frame: Frame, poly: Polygon) -> Optional[Bbox]:
        """Find bbox matching polygon using group_id or spatial mapping.
        
        In CVAT, a Bbox and a Polygon have different IDs. 
        Use group_id (preferred) or spatial mapping (same label + highest IoU).
        """
        # Try method 1: Match by group_id from attributes
        poly_group_id = poly.attributes.get('group_id')
        if poly_group_id:
            for b in frame.bboxes:
                if b.attributes.get('group_id') == poly_group_id:
                    return b
        
        # Try method 2: Spatial mapping - find bbox with same label and highest IoU
        poly_bbox = get_bbox_from_points(poly.points)
        best_match = None
        best_iou = 0.0
        
        for b in frame.bboxes:
            if b.label != poly.label:
                continue
            
            bbox_tuple = (b.xtl, b.ytl, b.xbr, b.ybr)
            poly_tuple = (poly_bbox[0], poly_bbox[1], poly_bbox[2], poly_bbox[3])
            iou = calculate_iou(bbox_tuple, poly_tuple)
            
            # Also check intersection over polygon area
            try:
                shapely_poly = ShapelyPoly(poly.points)
                poly_area = shapely_poly.area
                if poly_area > 0:
                    # Calculate intersection area
                    inter_x1 = max(bbox_tuple[0], poly_tuple[0])
                    inter_y1 = max(bbox_tuple[1], poly_tuple[1])
                    inter_x2 = min(bbox_tuple[2], poly_tuple[2])
                    inter_y2 = min(bbox_tuple[3], poly_tuple[3])
                    
                    if inter_x2 > inter_x1 and inter_y2 > inter_y1:
                        inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
                        # Use intersection over polygon area ratio
                        spatial_match_score = inter_area / poly_area
                        if spatial_match_score > best_iou:
                            best_iou = spatial_match_score
                            best_match = b
            except Exception:
                if iou > best_iou:
                    best_iou = iou
                    best_match = b
        
        return best_match

    def _is_mask_out_of_bbox(self, min_x: float, min_y: float, max_x: float, max_y: float,
                          box: Bbox) -> bool:
        """Check if mask bounds are outside bbox boundaries"""
        return (
            min_x < box.xtl - self.mask_tolerance or
            min_y < box.ytl - self.mask_tolerance or
            max_x > box.xbr + self.mask_tolerance or
            max_y > box.ybr + self.mask_tolerance
        )

    def _check_extreme_aspect_ratio(self, frame: Frame) -> List[Dict]:
        """Check for bounding boxes with extreme aspect ratios"""
        errors = []
        for box in frame.bboxes:
            ratio = calculate_aspect_ratio((box.xtl, box.ytl, box.xbr, box.ybr))
            if self._is_extreme_ratio(ratio):
                errors.append(self._create_bbox_error(
                    frame, box, "Extreme_Aspect_Ratio",
                    ratio=ratio
                ))
        return errors

    def _is_extreme_ratio(self, ratio: float) -> bool:
        """Check if aspect ratio is extreme"""
        return ratio > self.max_aspect_ratio or ratio < self.min_aspect_ratio

    def _check_label_consistency(self, frame: Frame) -> List[Dict]:
        """Check for label consistency"""
        errors = []
        label_hierarchy = self._get_label_hierarchy()
        
        for child_label, parent_labels in label_hierarchy.items():
            errors.extend(self._check_child_parent_consistency(frame, child_label, parent_labels))
        
        return errors

    def _get_label_hierarchy(self) -> Dict[str, List[str]]:
        """Get label hierarchy definitions.
        
        Based on label.json: pedestrian/person cannot be inside car/truck/bus
        """
        return {
            "pedestrian": ["car", "truck", "bus"],
            "person": ["car", "truck", "bus"]
        }

    def _check_child_parent_consistency(self, frame: Frame, child_label: str,
                                         parent_labels: List[str]) -> List[Dict]:
        """Check if child label objects are inside parent label objects"""
        errors = []
        
        # Safely get child boxes (handle None/empty)
        child_boxes = [b for b in frame.bboxes if b.label == child_label]
        
        for child in child_boxes:
            if child is None:
                continue
            try:
                errors.extend(self._check_child_against_parents(
                    frame, child, child_label, parent_labels
                ))
            except Exception:
                # Skip any errors and continue with other boxes
                continue
        return errors

    def _check_child_against_parents(self, frame: Frame, child: Bbox, child_label: str,
                                     parent_labels: List[str]) -> List[Dict]:
        """Check if a child box is inside any parent box"""
        errors = []
        
        if child is None:
            return errors
            
        child_box = (child.xtl, child.ytl, child.xbr, child.ybr)
        
        for parent_label in parent_labels:
            # Safely filter parent boxes
            parent_boxes = [b for b in frame.bboxes
                          if b is not None and b.label == parent_label and b.id != child.id]
            for parent in parent_boxes:
                if parent is None:
                    continue
                parent_box = (parent.xtl, parent.ytl, parent.xbr, parent.ybr)
                if self._is_child_in_parent(child_box, parent_box):
                    errors.append(generate_error_payload(
                        frame.name, child.id, "Label_Consistency",
                        [child.xtl, child.ytl, child.xbr, child.ybr],
                        child_label=child_label,
                        parent_label=parent_label
                    ))
        return errors

    def _is_child_in_parent(self, child_box: Tuple, parent_box: Tuple) -> bool:
        """Check if child box is inside parent box with high IoU"""
        return calculate_iou(child_box, parent_box) > 0.5
