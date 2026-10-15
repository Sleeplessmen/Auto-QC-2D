"""Review nhan cho CA ANH (tag), vd image_info voi thuoc tinh weather / timeofday / scene.

- Anh chua co tag -> ghi chu "thieu", kem gia tri tool nhin thay (CLIP)
- Da co tag -> doi chieu gia tri thuoc tinh voi CLIP; khac ro rang -> "co the sai"
Khong sua nhan, chi tra ve danh sach ghi chu giong review_core.compare.
"""
from label_mapping import norm

# cau mo ta cho CLIP theo gia tri hay gap (BDD100K va tuong tu); gia tri khac dung cau chung
PROMPTS = {
    "clear": "a dashcam photo on a clear sunny day", "sunny": "a dashcam photo on a clear sunny day",
    "partlycloudy": "a dashcam photo with a partly cloudy sky", "overcast": "a dashcam photo under a grey overcast sky",
    "cloudy": "a dashcam photo under a grey overcast sky", "rainy": "a dashcam photo in the rain with a wet road",
    "rain": "a dashcam photo in the rain with a wet road", "snowy": "a dashcam photo with snow on the street",
    "snow": "a dashcam photo with snow on the street", "foggy": "a dashcam photo in thick fog",
    "daytime": "a dashcam photo taken in daytime", "day": "a dashcam photo taken in daytime",
    "night": "a dashcam photo taken at night, dark sky", "dawndusk": "a dashcam photo taken at dusk or dawn",
    "citystreet": "a dashcam photo of a city street", "highway": "a dashcam photo on a highway",
    "residential": "a dashcam photo in a residential area", "tunnel": "a dashcam photo inside a tunnel",
    "parkinglot": "a dashcam photo of a parking lot", "gasstations": "a dashcam photo at a gas station",
}
WRONG_P = 0.6           # CLIP chon gia tri khac voi xac suat >= muc nay (va gia tri dang gan <= 0.15) -> co the sai
GUESS_P = 0.4           # du chac de goi y gia tri cho anh thieu tag


def frame_labels(labels, used_names):
    """Nhan gan cho ca anh: kieu 'tag', hoac co thuoc tinh chon (select / radio) va khong phai nhan box / vung."""
    out = []
    for lb in labels:
        if lb["name"] in used_names:
            continue
        sel = [a for a in lb.get("attributes", []) if a.get("input_type") in ("select", "radio") and len(a.get("values") or []) > 1]
        if lb.get("type") == "tag" or sel:
            out.append(dict(name=lb["name"], id=lb["id"], attrs=sel))
    return out


def _prompt(attr, v):
    return PROMPTS.get(norm(v)) or f"a dashcam photo, {attr}: {v}"


def check(img, tags, flabels, clf):
    """tags: tag cua 1 anh [dict(label_id, attributes=[{spec_id, value}])]. clf: CLIP (L.GreenSMClassifier) | None."""
    out = []
    H, W = img.shape[:2]
    band = [0.0, 0.0, float(W), float(min(H, 60))]           # Issue cho ca anh: dai mong sat mep tren
    for fl in flabels:
        mine = [t for t in tags if t["label_id"] == fl["id"]]
        guess = {}
        for a in fl["attrs"]:
            if clf is None:
                continue
            vals = a["values"]
            p = clf.probs(img, [[0, 0, W, H]], [_prompt(a["name"], v) for v in vals], pad=0)[0]
            guess[a["id"]] = (a["name"], vals, p)
        if not mine:
            hint = [f"{n} = '{vals[p.argmax()]}'" for n, vals, p in guess.values() if p.max() >= GUESS_P]
            out.append(dict(kind="thieu", sure=True, label=fl["name"], box=band, ref=None,
                            msg=f"Thiếu nhãn ảnh '{fl['name']}'" + (f" (ảnh trông là {', '.join(hint)})." if hint else ".")))
            continue
        t = mine[0]
        if len(mine) > 1:
            out.append(dict(kind="trung", sure=True, label=fl["name"], box=band, ref=f"tag {mine[1]['id']}",
                            msg=f"Trùng: ảnh có {len(mine)} nhãn '{fl['name']}', chỉ giữ 1."))
        cur = {x["spec_id"]: x["value"] for x in t.get("attributes", [])}
        for sid, (name, vals, p) in guess.items():
            v = cur.get(sid)
            if v not in vals:
                continue
            k = int(p.argmax())
            if vals[k] != v and p[k] >= WRONG_P and p[vals.index(v)] <= 0.15:
                out.append(dict(kind="sai_nhan", sure=False, label=fl["name"], box=band, ref=f"tag {t['id']}",
                                msg=f"Có thể sai {name}: đang chọn '{v}', ảnh trông là '{vals[k]}'."))
    return out
