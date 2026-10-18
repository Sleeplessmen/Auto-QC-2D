from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class Bbox:
    id: int
    label: str
    xtl: float  # x top left (x_min)
    ytl: float  # y top left (y_min)
    xbr: float  # x bottom right (x_max)
    ybr: float  # y bottom right (y_max)
    attributes: Dict[str, str] = field(default_factory=dict)

@dataclass
class Polygon:
    id: int
    label: str
    points: List[tuple]  # Danh sách các điểm [(x1,y1), (x2,y2), ...]
    attributes: Dict[str, str] = field(default_factory=dict)

@dataclass
class FrameTag:
    label: str
    attributes: Dict[str, str] = field(default_factory=dict)

@dataclass
class Frame:
    frame_id: int
    width: int
    height: int
    name: str
    bboxes: List[Bbox] = field(default_factory=list)
    polygons: List[Polygon] = field(default_factory=list)
    tags: List[FrameTag] = field(default_factory=list)