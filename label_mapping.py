"""Khớp kết quả model với bộ nhãn THẬT của task CVAT — hỗ trợ cả 2 kiểu tài liệu:

  Kiểu A (AI20K):  nhãn riêng cho từng loại — "area/drivable", "area/alternative", "lane/single white"...
  Kiểu B (BDD):    1 nhãn + thuộc tính — "drivable_area" {areaType: direct|alternative, needs_review},
                   "lane_marking" {Types: crosswalk|single white|..., Style: solid|dashed, Direction: ...}

Tên nhãn/thuộc tính/giá trị được so sánh sau khi bỏ hoa thường, dấu cách, "_", "-", "/". Không khớp được
thì trả về None + lý do (không đoán bừa nhãn).
"""
import re

AREA_LABELS_A = {"direct": "area/drivable", "alternative": "area/alternative"}
AREA_TYPE_VALUES = {"direct": ("direct", "drivable"), "alternative": ("alternative", "alternate")}
LANE_TYPE_VALUES = {   # tên nhãn nội bộ -> các cách viết giá trị "Types" hay gặp
    "lane/crosswalk": ("crosswalk",),
    "lane/single white": ("single white", "singlewhite", "white single"),
    "lane/single yellow": ("single yellow",),
    "lane/double white": ("double white",),
    "lane/double yellow": ("double yellow",),
    "lane/road curb": ("road curb", "curb"),
    "lane/single other": ("single other",),
}
TRUE_VALUES = ("true", "yes", "1", "co")
FALSE_VALUES = ("false", "no", "0", "khong")


def norm(s):
    s = s.lower().replace("đ", "d")
    for a, b in (("ó", "o"), ("ô", "o"), ("ơ", "o"), ("á", "a"), ("à", "a"), ("ạ", "a")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", s)


def _find_label(schema, *keywords, exclude=()):
    for name, label in schema.items():
        n = norm(name)
        if any(k in n for k in keywords) and not any(x in n for x in exclude):
            return label
    return None


def _find_attr(label, *keywords):
    for name, spec_id in label["attributes"].items():
        if any(k in norm(name) for k in keywords):
            return name, spec_id
    return None


def _match(values, wanted):
    """Giá trị trong danh sách khớp 1 trong các cách viết mong muốn (khớp nguyên văn trước, rồi chứa nhau)."""
    wn = [norm(x) for x in wanted]
    for v in values:
        if norm(v) in wn:
            return v
    for v in values:
        if any(w and (w in norm(v)) for w in wn):
            return v
    return None


def _set_attr(label, attrs, keywords, wanted, required, errors, what):
    found = _find_attr(label, *keywords)
    if found is None:
        if required:
            errors.append(f"nhãn không có thuộc tính {what}")
        return
    name, spec_id = found
    values = label.get("attr_values", {}).get(name, [])
    if not values or all(norm(v) in ("true", "false") for v in values):   # checkbox / text: CVAT nhận chuỗi
        attrs.append({"spec_id": spec_id, "value": wanted[0]})
        return
    v = _match(values, wanted)
    if v is None:
        errors.append(f"thuộc tính {name} không có giá trị cho '{wanted[0]}' (có: {values})")
        return
    attrs.append({"spec_id": spec_id, "value": v})


def _review_attr(label, attrs, needs_review):
    errors = []
    _set_attr(label, attrs, ("review",), TRUE_VALUES if needs_review else FALSE_VALUES, False, errors, "needs_review")


def resolve_drivable(schema, area_type, needs_review):
    """Trả về (label_id, attributes) hoặc (None, lý do)."""
    attrs, errors = [], []
    label = schema.get(AREA_LABELS_A[area_type])
    if label is None:
        label = _find_label(schema, "drivable")
        if label is None:
            return None, f"task không có nhãn drivable cho '{area_type}'"
        _set_attr(label, attrs, ("areatype", "type"), AREA_TYPE_VALUES[area_type], True, errors, "areaType")
        if errors:
            return None, "; ".join(errors)
    _review_attr(label, attrs, needs_review)
    return label["id"], attrs


def resolve_lane(schema, name, style=None, along=None):
    """name: tên nội bộ "lane/..." . Trả về (label_id, attributes) hoặc (None, lý do)."""
    attrs, errors = [], []
    label = schema.get(name)
    if label is None:
        label = _find_label(schema, "lane", "marking", exclude=("drivable",))
        if label is None:
            return None, f"task không có nhãn cho '{name}'"
        _set_attr(label, attrs, ("type", "category", "class"), LANE_TYPE_VALUES.get(name, (name,)), True, errors, "Types")
        if errors:
            return None, "; ".join(errors)
    if style:
        _set_attr(label, attrs, ("style",), (style, "dash" if style == "dashed" else style), False, errors, "Style")
    if along is not None:
        _set_attr(label, attrs, ("direction",), ("parallel",) if along else ("vertical",), False, errors, "Direction")
    return label["id"], attrs
