"""
guideline.py — Doc file Guideline (PDF / DOCX / TXT / MD), chia muc, tim doan lien quan toi 1 nhan,
va file LUAT (YAML) de tool kiem tra tu dong (tang 1) + chinh tang 2 (ten nhan, nguoi lai xe may).

File luat (vi du):
  nhan:
    car:                              # ten nhan dung nhu trong CVAT
      loai_tool: car                  # tool hieu nhan nay la gi: car truck bus motorcycle bicycle person GreenSM
      dong_nghia: [oto, xe hoi]       # ten khac goi nhan nay trong guideline (de tim doan lien quan)
      kich_thuoc_toi_thieu_px: 10     # canh ngan nho hon -> loi
      ti_le_rong_cao: [0.4, 4.0]      # rong/cao ngoai khoang -> "khong chac"
      thuoc_tinh_bat_buoc: [occluded] # de trong -> loi
      khong_de_mac_dinh: []           # con gia tri mac dinh -> "khong chac" (co the quen chon)
      muc: "3.1"                      # muc guideline noi ve nhan nay (ghi vao Issue)
  quy_tac:
    nguoi_lai_co_box_rieng: true      # nguoi lai xe may phai co box person rieng
    khong_bat_buoc_duoi_px: 10        # vat co canh ngan nho hon -> KHONG bat buoc gan (tool khong bao thieu),
                                      #   da gan thi van hop le (khac kich_thuoc_toi_thieu_px: box nho hon la loi)
    box_ra_ngoai_anh_px: 2            # box vuot mep anh qua N px -> loi
    nhan_ngoai_guideline: false       # true -> moi box co nhan khong co trong guideline deu bi ghi chu
    kieu_nhan: shape                  # shape = anh roi (moi vat 1 shape, vd BDD100K) | track = video (1 vat 1 track)
    polygon_kem_box: trung            # 1 vat vua co box vua co polygon/mask: trung = loi trung (chi can 1),
                                      #   cap = instance segmentation (moi vat box + polygon, polygon phai nam trong box)
    muc_chung: "2"
"""

import os
import re

import unicodedata
import zipfile
import xml.etree.ElementTree as ET

import yaml

TOOL_CLASSES = ["car", "truck", "bus", "motorcycle", "bicycle", "person", "GreenSM"]


# ---------------------------------------------------------------- doc file
def extract_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".md", ".yaml", ".yml"):
        raw = open(path, "rb").read()
        for enc in ("utf-8-sig", "utf-16", "cp1258", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                pass
    if ext == ".pdf":
        from pypdf import PdfReader
        pages = []
        for i, p in enumerate(PdfReader(path).pages, 1):
            pages.append(f"[Trang {i}]\n" + (p.extract_text() or ""))
        return "\n".join(pages)
    if ext == ".docx":
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("word/document.xml"))
        paras = []
        for p in root.iter(ns + "p"):
            t = "".join(x.text or "" for x in p.iter(ns + "t"))
            style = p.find(f"{ns}pPr/{ns}pStyle")
            if style is not None and "heading" in (style.get(ns + "val") or "").lower() and t.strip():
                t = "# " + t
            paras.append(t)
        return "\n".join(paras)
    raise ValueError(f"Chưa đọc được file {ext}. Dùng PDF, DOCX, TXT hoặc MD.")


def fold(s):
    """bo dau tieng Viet + chu thuong de tim kiem"""
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


HEAD_RE = re.compile(r"^\s*(#{1,6}\s+.+|(\d+(\.\d+){0,4})[.)]?\s+\S.{0,100}|(chương|chuong|phần|phan|mục|muc)\s+\S.{0,100})$",
                     re.IGNORECASE)


def sections(text):
    """[(muc, tieu de, noi dung)] — chia theo dong tieu de (# ..., 3.1 ..., Chuong ...)"""
    out, cur_t, cur_b = [], "Đầu tài liệu", []
    for line in (text or "").splitlines():
        s = line.strip()
        if s and len(s) <= 110 and HEAD_RE.match(s) and not s.endswith((",", ";")):
            if any(x.strip() for x in cur_b) or out == []:
                out.append((cur_t, "\n".join(cur_b).strip()))
            cur_t, cur_b = s.lstrip("# ").strip(), []
        else:
            cur_b.append(line)
    out.append((cur_t, "\n".join(cur_b).strip()))
    res = []
    for t, b in out:
        if not b.strip() and (not t.strip() or t == "Đầu tài liệu"):
            continue
        m = re.match(r"(\d+(\.\d+)*)", t)
        res.append(dict(muc=m.group(1) if m else "", title=t, body=b))
    return res


def find_related(text, words, limit=4, width=420):
    """Cac muc guideline nhac toi 1 trong cac tu (ten nhan, dong nghia). Tra ve [(muc, tieu de, doan trich)]."""
    keys = [fold(w) for w in words if w and len(w.strip()) >= 2]
    if not keys or not text:
        return []
    scored = []
    for sec in sections(text):
        ft, fb = fold(sec["title"]), fold(sec["body"])
        pat = [re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])") for k in keys]
        hits_t = sum(bool(p.search(ft)) for p in pat)
        hits_b = sum(len(p.findall(fb)) for p in pat)
        if not (hits_t or hits_b):
            continue
        pos = min((m.start() for p in pat for m in [p.search(fb)] if m), default=0)
        a = max(0, pos - width // 3)
        snip = sec["body"][a:a + width].strip()
        scored.append((hits_t * 5 + hits_b, dict(muc=sec["muc"], title=sec["title"],
                                                 snippet=("…" if a else "") + snip + ("…" if a + width < len(sec["body"]) else ""))))
    scored.sort(key=lambda x: -x[0])
    return [d for _, d in scored[:limit]]


# ---------------------------------------------------------------- file luat
def parse_rules(txt):
    """Tra ve (rules dict, [canh bao]). Loi cu phap -> ValueError co dong loi."""
    if not (txt or "").strip():
        return {}, []
    try:
        r = yaml.safe_load(txt) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"File luật sai cú pháp YAML: {e}")
    if not isinstance(r, dict):
        raise ValueError("File luật phải có dạng 'nhan:' và 'quy_tac:'.")
    warn = []
    nhan = r.get("nhan") or {}
    if not isinstance(nhan, dict):
        raise ValueError("'nhan' phải là danh sách tên nhãn: mỗi nhãn một mục.")
    for name, spec in nhan.items():
        spec = spec or {}
        if not isinstance(spec, dict):
            raise ValueError(f"Nhãn '{name}': phải là các dòng 'khoá: giá trị'.")
        lt = spec.get("loai_tool")
        if lt and lt not in TOOL_CLASSES:
            warn.append(f"Nhãn '{name}': loai_tool '{lt}' không có. Chọn một trong: {', '.join(TOOL_CLASSES)}.")
        rr = spec.get("ti_le_rong_cao")
        if rr is not None and not (isinstance(rr, list) and len(rr) == 2 and all(isinstance(v, (int, float)) for v in rr)):
            warn.append(f"Nhãn '{name}': ti_le_rong_cao phải dạng [nhỏ nhất, lớn nhất], ví dụ [0.4, 4.0].")
        for k in ("thuoc_tinh_bat_buoc", "khong_de_mac_dinh", "dong_nghia"):
            if spec.get(k) is not None and not isinstance(spec.get(k), list):
                warn.append(f"Nhãn '{name}': {k} phải là danh sách, ví dụ [occluded, truncated].")
        nhan[name] = spec
    r["nhan"] = nhan
    r["quy_tac"] = r.get("quy_tac") or {}
    return r, warn


def template_from_labels(labels, guess=None):
    """labels: nhan cua task tren CVAT (co attributes). guess: {ten nhan: lop tool} tu review_core.build_label_map."""
    guess = guess or {}
    nhan = {}
    for lb in labels:
        spec = {}
        if guess.get(lb["name"]):
            spec["loai_tool"] = guess[lb["name"]]
        spec["dong_nghia"] = []
        spec["kich_thuoc_toi_thieu_px"] = 0
        attrs = [a["name"] for a in lb.get("attributes", [])]
        spec["thuoc_tinh_bat_buoc"] = []
        if attrs:
            spec["khong_de_mac_dinh"] = []
        spec["muc"] = ""
        nhan[lb["name"]] = spec
    head = ("# File luat guideline — sua cac gia tri cho dung guideline cua du an.\n"
            "# Thuoc tinh cua tung nhan tren CVAT: " +
            "; ".join(f"{lb['name']}: {', '.join(a['name'] for a in lb.get('attributes', [])) or '-'}" for lb in labels) + "\n")
    body = dict(nhan=nhan, quy_tac=dict(nguoi_lai_co_box_rieng=True, box_ra_ngoai_anh_px=2,
                                        nhan_ngoai_guideline=False, kieu_nhan="", polygon_kem_box="trung", muc_chung=""))
    return head + yaml.safe_dump(body, allow_unicode=True, sort_keys=False)


def _spec_for(rules, label):
    nhan = rules.get("nhan") or {}
    if label in nhan:
        return nhan[label]
    from label_mapping import norm
    n = norm(label)
    for k, v in nhan.items():
        if norm(k) == n or n in [norm(s) for s in (v.get("dong_nghia") or [])]:
            return v
    return None


def words_for(rules, label):
    spec = _spec_for(rules or {}, label) or {}
    return [label, label.replace("_", " ")] + list(spec.get("dong_nghia") or [])


def muc_ref(rules, label, extra=""):
    spec = _spec_for(rules or {}, label) or {}
    m = spec.get("muc") or (rules or {}).get("quy_tac", {}).get("muc_chung") or ""
    return f" — Guideline mục {m}" if m else (f" — {extra}" if extra else "")


# ---------------------------------------------------------------- tu doc yeu cau trong guideline -> file luat
# ten goi thuong gap (da bo dau) cua tung loai vat, de biet 1 cau guideline dang noi ve nhan nao
VI_NAMES = {
    "car": ["o to", "oto", "xe hoi", "xe con", "xe du lich", "car", "cars", "vehicle", "xe 4 banh"],
    "truck": ["xe tai", "truck", "xe ben", "container"], "bus": ["xe buyt", "xe bus", "xe khach", "bus"],
    "motorcycle": ["xe may", "xe moto", "motorcycle", "motorbike", "scooter", "xe 2 banh"],
    "bicycle": ["xe dap", "bicycle", "bike"],
    "person": ["nguoi di bo", "nguoi", "pedestrian", "person", "khach bo hanh"],
    "road": ["mat duong", "vung duong", "lan duong", "duong di", "drivable", "road"],
}
_NUM_PX = r"(\d{1,3})\s*(?:px|pixel|pixels|diem anh|điểm ảnh)"
MIN_RE = [re.compile(r"(?:nho hon|be hon|duoi|it hon|< ?|smaller than|less than|under|below)\s*" + _NUM_PX),
          re.compile(r"(?:toi thieu|it nhat|minimum|min(?:imum)? size|at least|>= ?)\s*(?:la\s*)?" + _NUM_PX)]
AMODAL_YES = ["toan bo vat", "ca phan bi che", "phan bi che", "uoc luong", "amodal", "full extent", "bao tron vat",
              "ve het vat", "ve ca phan", "whole object", "entire object"]
AMODAL_NO = ["chi ve phan nhin thay", "phan nhin thay", "phan nhin thay duoc", "visible part", "only the visible",
             "khong ve phan bi che", "khong uoc luong"]
NEG = re.compile(r"(?:khong|ko|không|chua|not|don't|do not|never)\s+(?:\S+\s+){0,3}$")


def _sentences(text):
    """[(muc, cau goc, cau da bo dau, la tieu de?, tieu de muc nay + cac muc cha da bo dau)]"""
    out, titles, muc = [], {}, ""

    def ctx_of(m):
        c = []
        while m:                                   # 2.1 -> tieu de 2.1, roi 2 (muc cha)
            c.append(titles.get(m, ""))
            m = m.rsplit(".", 1)[0] if "." in m else ""
        return c

    for line in (text or "").splitlines():
        s = line.strip()
        is_head = bool(s) and len(s) <= 110 and HEAD_RE.match(s) and not s.endswith((",", ";"))
        if is_head:
            mm = re.match(r"#*\s*(\d+(\.\d+)*)", s)
            muc = mm.group(1) if mm else muc
            titles[muc] = fold(s)
        for k, part in enumerate(re.split(r"(?<=[.;!?])\s+", s)):
            p = part.strip(" -•*\t#")
            if len(p) >= 6:
                out.append((muc, p, fold(p), is_head and k == 0, ctx_of(muc)))
    return out


def _mentions(fs, label, tool_cls):
    keys = {fold(label), fold(label.replace("_", " "))} | set(VI_NAMES.get(tool_cls or "", []))
    return any(re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", fs) for k in keys if k)


def _has(fs, phrases):
    """co cum tu ma khong bi phu dinh ngay truoc"""
    for p in phrases:
        i = fs.find(p)
        if i >= 0 and not NEG.search(fs[max(0, i - 30):i]):
            return True
    return False


def extract_rules(text, labels, guess=None):
    """Doc guideline (van ban) -> (rules dict giong file luat, [dict(luat, gia_tri, muc, trich)]) de nguoi QC kiem lai.
    labels: nhan cua task tren CVAT. guess: {ten nhan: lop tool | 'road'}."""
    guess = guess or {}
    names = [lb["name"] for lb in labels]
    nhan = {n: {} for n in names}
    q, ev = {}, []

    def note(rule, val, muc, quote):
        ev.append(dict(luat=rule, gia_tri=val, muc=muc, trich=quote[:220]))

    for muc, raw, fs, is_title, ctx in _sentences(text or ""):
        about = [n for n in names if _mentions(fs, n, guess.get(n))]
        if is_title and about and muc:             # muc co tieu de noi ve nhan -> muc cua nhan do
            for n in about:
                nhan[n]["muc"] = muc
        if not about:                              # cau khong nhac nhan nao -> hieu theo tieu de muc / muc cha
            for t in ctx:
                about = [n for n in names if _mentions(t, n, guess.get(n))]
                if about:
                    break
        # 1) kich thuoc toi thieu
        for rx in MIN_RE:
            m = rx.search(fs)
            if not m:
                continue
            px = int(m.group(1))
            if not 2 <= px <= 200 or not any(w in fs for w in ("box", "vat", "doi tuong", "object", "gan", "label", "ve", "bo qua", "ignore", "khong")):
                continue
            # "vat nho hon N px KHONG BAT BUOC gan" -> chi bo yeu cau gan, box nho da gan khong phai loi
            if any(w in fs for w in ("khong bat buoc", "not required", "optional", "tuy chon")) and "khong_bat_buoc_duoi_px" not in q:
                q["khong_bat_buoc_duoi_px"] = px
                note("khong_bat_buoc_duoi_px", f"vật dưới {px} px không bắt buộc gán", muc, raw)
                break
            targets = [n for n in about if guess.get(n) != "road"] or [n for n in names if guess.get(n) not in (None, "road")]
            for n in targets:
                if not nhan[n].get("kich_thuoc_toi_thieu_px"):
                    nhan[n]["kich_thuoc_toi_thieu_px"] = px
                    nhan[n].setdefault("muc", muc)
            note("kich_thuoc_toi_thieu_px", f"{px} px" + (f" ({', '.join(targets)})" if about else " (mọi nhãn box)"), muc, raw)
            break
        # 2) ve toan bo vat (ca phan bi che) hay chi phan nhin thay
        if "toan_bo_vat" not in q:
            if _has(fs, AMODAL_NO):
                q["toan_bo_vat"] = False
                note("toan_bo_vat", "chỉ vẽ phần nhìn thấy", muc, raw)
            elif _has(fs, AMODAL_YES) and any(w in fs for w in ("che", "khuat", "occlu", "box", "ve")):
                q["toan_bo_vat"] = True
                note("toan_bo_vat", "vẽ toàn bộ vật, cả phần bị che", muc, raw)
        # 3) nguoi lai xe may
        if "nguoi_lai_co_box_rieng" not in q and re.search(r"nguoi (lai|ngoi)|rider|driver|nguoi tren xe", fs):
            if re.search(r"khong (can )?(gan|ve)|gop chung|chung (1 )?box|khong tach|do not label|not labeled", fs):
                q["nguoi_lai_co_box_rieng"] = False
                note("nguoi_lai_co_box_rieng", "không", muc, raw)
            elif re.search(r"box (\S+ )?rieng|gan (\S+ )?rieng|tach rieng|ve rieng|separate", fs):
                q["nguoi_lai_co_box_rieng"] = True
                note("nguoi_lai_co_box_rieng", "có", muc, raw)
        # 4) box khong ra ngoai anh
        if "box_ra_ngoai_anh_px" not in q and re.search(r"(khong|not)\s+(\S+\s+){0,3}(ra ngoai|vuot|outside)\s+(\S+\s+){0,2}(anh|khung|image|frame)", fs):
            q["box_ra_ngoai_anh_px"] = 1
            note("box_ra_ngoai_anh_px", "box không được ra ngoài ảnh", muc, raw)
        # 5) instance segmentation: moi vat vua box vua polygon / mask
        if "polygon_kem_box" not in q:
            if re.search(r"instance segmentation|(box|bbox) (va|kem|cung) (polygon|mask)|(polygon|mask) (va|kem|cung) (box|bbox)", fs) \
                    and not NEG.search(fs[:40]):
                q["polygon_kem_box"] = "cap"
                note("polygon_kem_box", "mỗi vật vừa box vừa polygon/mask (instance segmentation)", muc, raw)
            elif re.search(r"(chi|only) (\S+ )?(1|mot|one) (trong 2|loai)|khong (ve|gan) (ca )?(box|bbox) (cho|voi) (vat|doi tuong) (da )?(co )?(polygon|mask)", fs):
                q["polygon_kem_box"] = "trung"
                note("polygon_kem_box", "mỗi vật chỉ box HOẶC polygon/mask", muc, raw)
        # 6) shape hay track
        if "kieu_nhan" not in q and re.search(r"\b(shape|track|interpolation|noi suy)\b", fs):
            if re.search(r"(dung|gan|ve|use|annotate)\s+(\S+\s+){0,3}shape|khong (dung|gan) (\S+ )?track|(anh|image)s? (roi|rieng|doc lap|independent)", fs):
                q["kieu_nhan"] = "shape"
                note("kieu_nhan", "gán bằng Shape (ảnh rời)", muc, raw)
            elif re.search(r"(dung|gan|ve|use|annotate)\s+(\S+\s+){0,3}(track|interpolation)|noi suy|qua cac (frame|khung)", fs):
                q["kieu_nhan"] = "track"
                note("kieu_nhan", "gán bằng Track (video)", muc, raw)
        # 7) thuoc tinh bat buoc
        if re.search(r"bat buoc|phai chon|phai gan|phai danh dau|luon chon|must|required|mandatory", fs):
            for lb in labels:
                for a in lb.get("attributes", []):
                    an = fold(a["name"])
                    if re.search(r"(?<![a-z0-9])" + re.escape(an) + r"(?![a-z0-9])", fs) and (not about or lb["name"] in about):
                        lst = nhan[lb["name"]].setdefault("thuoc_tinh_bat_buoc", [])
                        if a["name"] not in lst:
                            lst.append(a["name"])
                            note("thuoc_tinh_bat_buoc", f"{lb['name']}: {a['name']}", muc, raw)
    for n in names:
        if guess.get(n) and guess[n] != "road":
            nhan[n]["loai_tool"] = guess[n]
        syn = [w for w in VI_NAMES.get(guess.get(n) or "", []) if w in fold(text or "") and w != fold(n)]
        if syn:
            nhan[n]["dong_nghia"] = syn[:4]
    return dict(nhan=nhan, quy_tac=q), ev


# ---------------------------------------------------------------- tang 1: kiem tra theo luat
def _rect(points):
    xs, ys = points[0::2], points[1::2]
    return [min(xs), min(ys), max(xs), max(ys)]


def _bbox(points, kind):
    p = [float(v) for v in points]
    if kind == "mask":                  # RLE + [left, top, right, bottom]
        return [p[-4], p[-3], p[-2] + 1, p[-1] + 1]
    return [min(p[0::2]), min(p[1::2]), max(p[0::2]), max(p[1::2])]


def rule_check(ann, labels, frames, rules):
    """ann: annotations cua job (CVAT API). labels: nhan cua task. frames: [(so frame, ten anh, w, h)].
    Tra ve (findings, canh bao). Moi finding giong review_core: kind, sure, label, box, ref, msg, frame, name."""
    if not rules or not (rules.get("nhan") or rules.get("quy_tac")):
        return [], []
    q = rules.get("quy_tac") or {}
    tol = float(q.get("box_ra_ngoai_anh_px", 2) or 0)
    id2lb = {lb["id"]: lb for lb in labels}
    spec2attr = {a["id"]: a for lb in labels for a in lb.get("attributes", [])}
    fr = {n: (name, w, h) for n, name, w, h in frames}
    out, warn = [], []
    missing = sorted({lb["name"] for lb in labels if _spec_for(rules, lb["name"]) is None})
    if missing and rules.get("nhan"):
        warn.append("Nhãn có trong task nhưng không có trong file luật: " + ", ".join(missing))

    def check(obj_id, label_id, frame, points, attrs, rotation, kind="rectangle"):
        if frame not in fr or label_id not in id2lb:
            return
        name, W, H = fr[frame]
        lb = id2lb[label_id]["name"]
        box = _rect(points) if kind == "rectangle" else _bbox(points, kind)
        bw, bh = box[2] - box[0], box[3] - box[1]
        what = {"rectangle": "Box", "polygon": "Polygon", "mask": "Mask"}[kind]
        spec = _spec_for(rules, lb)
        ref = muc_ref(rules, lb)
        base = dict(kind="guideline", label=lb, box=box, ref=obj_id, frame=frame, name=os.path.basename(name), tang=1)
        if spec is None:
            if q.get("nhan_ngoai_guideline"):
                out.append(dict(base, sure=True, msg=f"Nhãn '{lb}' không có trong guideline{muc_ref(rules, '')}."))
            return
        if bw < 1 or bh < 1:
            out.append(dict(base, sure=True, msg=f"{what} '{lb}' gần như không có diện tích ({bw:.0f}x{bh:.0f} px){ref}."))
            return
        if W and H and tol and (box[0] < -tol or box[1] < -tol or box[2] > W + tol or box[3] > H + tol):
            out.append(dict(base, sure=True, msg=f"{what} '{lb}' vượt ra ngoài ảnh{ref}."))
        mn = float(spec.get("kich_thuoc_toi_thieu_px") or 0)
        if mn and min(bw, bh) < mn:
            out.append(dict(base, sure=True, msg=f"{what} '{lb}' nhỏ hơn mức tối thiểu ({min(bw, bh):.0f} < {mn:.0f} px){ref}."))
        rr = spec.get("ti_le_rong_cao")
        if isinstance(rr, list) and len(rr) == 2 and not abs(rotation or 0) > 0.5:
            ar = bw / max(bh, 1e-6)
            if ar < rr[0] or ar > rr[1]:
                out.append(dict(base, sure=False, msg=f"{what} '{lb}' có tỉ lệ rộng/cao {ar:.2f}, ngoài khoảng {rr[0]}–{rr[1]}{ref}."))
        vals = {}
        for a in attrs or []:
            sp = spec2attr.get(a.get("spec_id"))
            if sp:
                vals[sp["name"]] = (a.get("value"), sp)
        for an in spec.get("thuoc_tinh_bat_buoc") or []:
            v = vals.get(an)
            if v is None or str(v[0]).strip() == "":
                out.append(dict(base, sure=True, msg=f"{what} '{lb}' thiếu thuộc tính '{an}'{ref}."))
        for an in spec.get("khong_de_mac_dinh") or []:
            v = vals.get(an)
            if v is not None and str(v[0]) == str(v[1].get("default_value")):
                out.append(dict(base, sure=False, msg=f"{what} '{lb}': thuộc tính '{an}' vẫn để mặc định '{v[0]}', kiểm tra đã chọn chưa{ref}."))

    for s in ann.get("shapes", []):
        if s.get("type") in ("rectangle", "polygon", "mask"):
            check(f"shape {s['id']}", s["label_id"], s["frame"], s["points"], s.get("attributes"), s.get("rotation"), s["type"])
    for t in ann.get("tracks", []):
        for k in t.get("shapes", []):
            if k.get("type", "rectangle") in ("rectangle", "polygon", "mask") and not k.get("outside"):
                check(f"track {t['id']}", t["label_id"], k["frame"], k["points"],
                      list(t.get("attributes") or []) + list(k.get("attributes") or []), k.get("rotation"),
                      k.get("type", "rectangle"))
    return out, warn


# ---------------------------------------------------------------- tang 2: dua luat vao review_core
class apply_to_core:
    """with apply_to_core(rules, R): ... — them ten nhan cua guideline vao bang dong nghia cua tool trong luc review."""

    def __init__(self, rules, R):
        self.rules, self.R, self.saved = rules or {}, R, None

    def __enter__(self):
        from label_mapping import norm
        self.saved = {k: list(v) for k, v in self.R.SYN.items()}
        import area_check
        self.area_check = area_check
        self.saved_amodal, self.saved_min = self.R.AMODAL, dict(self.R.MIN_MISS_BY_LABEL)
        self.saved_side = self.R.MIN_MISS_SIDE
        self.saved_pair, self.saved_kieu = area_check.MASK_WITH_BOX, self.R.KIEU_NHAN
        q = self.rules.get("quy_tac") or {}
        if q.get("polygon_kem_box") in ("cap", "trung"):   # quy uoc 1 vat vua box vua polygon
            area_check.MASK_WITH_BOX = q["polygon_kem_box"]
        if q.get("kieu_nhan") in ("shape", "track"):        # guideline noi gan bang shape hay track
            self.R.KIEU_NHAN = q["kieu_nhan"]
        if q.get("toan_bo_vat") is not None:            # guideline noi ve toan bo vat hay chi phan nhin thay
            self.R.AMODAL = bool(q["toan_bo_vat"])
        try:                                            # vat nho hon N px khong bat buoc gan -> tool bao thieu tu N px
            px = float(q.get("khong_bat_buoc_duoi_px") or 0)
        except (TypeError, ValueError):
            px = 0
        if px > 0:
            self.R.MIN_MISS_SIDE = px
        for name, spec in (self.rules.get("nhan") or {}).items():
            mn = (spec or {}).get("kich_thuoc_toi_thieu_px")
            if mn:                                      # guideline bo qua vat nho -> tool khong doi gan vat nho
                self.R.MIN_MISS_BY_LABEL[name] = float(mn)
        for name, spec in (self.rules.get("nhan") or {}).items():
            lt = (spec or {}).get("loai_tool")
            if lt in self.R.SYN:
                for w in [name] + list(spec.get("dong_nghia") or []):
                    n = norm(str(w))
                    if n and n not in self.R.SYN[lt]:
                        self.R.SYN[lt].insert(0, n)
        return self

    def __exit__(self, *a):
        self.R.SYN.clear()
        self.R.SYN.update(self.saved)
        self.R.AMODAL = self.saved_amodal
        self.area_check.MASK_WITH_BOX = self.saved_pair
        self.R.KIEU_NHAN = self.saved_kieu
        self.R.MIN_MISS_BY_LABEL.clear()
        self.R.MIN_MISS_BY_LABEL.update(self.saved_min)
        self.R.MIN_MISS_SIDE = self.saved_side


def rider_rule(rules, default=True):
    v = (rules or {}).get("quy_tac", {}).get("nguoi_lai_co_box_rieng")
    return default if v is None else bool(v)


def rules_to_yaml(obj):
    """Doi tuong tu trinh soan luat dang bang -> YAML gon (bo cac o de trong)."""
    def clean(v):
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items() if x not in (None, "", [], {}) and not (isinstance(x, (int, float)) and not isinstance(x, bool) and x == 0)}
        if isinstance(v, list):
            return [clean(x) for x in v if x not in (None, "")]
        return v
    obj = obj or {}
    out = {"nhan": {name: clean(spec or {}) for name, spec in (obj.get("nhan") or {}).items()},
           "quy_tac": clean(obj.get("quy_tac") or {})}
    for name in out["nhan"]:
        if out["nhan"][name] == {}:
            out["nhan"][name] = None
    return yaml.safe_dump(out, allow_unicode=True, sort_keys=False)
