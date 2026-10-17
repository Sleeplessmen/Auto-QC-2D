"""Test dau cuoi tren CVAT (ket noi so 2 cua web QC, mac dinh CVAT localhost): tao task BDD100K (box + polygon), cai 10 loi,
web QC review (ban sao du lieu web, khong dung toi lich su that), day Issue, gia lap annotator sua 1 phan + reviewer them
Issue, do hieu qua, review vong 2.
    venv\\Scripts\\python cvat_2d\\kiem_thu\\test_e2e_bdd.py      (ket qua: kiem_thu/ket_qua/e2e_result.json)"""
import json, os, shutil, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.dirname(HERE)                                         # cvat_2d
DATA = os.path.join(D, "du_lieu_danh_gia")                         # trong repo (cvat_2d/du_lieu_danh_gia)
if not os.path.isdir(DATA):
    DATA = os.path.join(os.path.dirname(D), "du_lieu_danh_gia")        # tood qc 2d/du_lieu_danh_gia
SP = os.path.join(HERE, "ket_qua")
os.makedirs(SP, exist_ok=True)
sys.path.insert(0, D); sys.path.insert(0, os.path.join(D, "web_qc")); os.chdir(D)
for f in (sys.stdout, sys.stderr):
    f.reconfigure(encoding="utf-8")

# ---- ban sao du lieu web (khong dung toi lich su that)
import store
SHADOW = os.path.join(SP, "e2e_data")
shutil.rmtree(SHADOW, ignore_errors=True)
shutil.copytree(store.DATA, SHADOW, ignore=shutil.ignore_patterns("uploads"))
store.DATA, store.DB_PATH = SHADOW, os.path.join(SHADOW, "web_qc.db")
store.init()
store.set_settings(auto_validation=False, webhook_enabled=False)

import cv2, numpy as np, requests
import review_core as R, label_hq_2d as L, guideline as G
import worker as Wm

conn = store.get_connection(2)
cv = R.Cvat(conn["url"], conn["token"])
url = conn["url"].rstrip("/")
s = cv.s
IM = os.path.join(DATA, "bdd_e2e")
names = ["b27098c3-c443b6e3.jpg", "b7ad4512-5b2510d8.jpg", "c323201c-9bcf7cf8.jpg", "c752e922-ae691e9d.jpg"]
labels_def = json.load(open(os.path.join(D, "guideline_bdd100k", "labels_bdd100k.json"), encoding="utf-8"))

# ---- 1. tao task
r = s.post(f"{url}/api/tasks", json=dict(name=f"e2e BDD100K det+insseg {time.strftime('%H%M%S')}", labels=labels_def))
r.raise_for_status()
tid = r.json()["id"]
files = [(f"client_files[{i}]", (n, open(os.path.join(IM, "images", n), "rb"))) for i, n in enumerate(names)]
r = s.post(f"{url}/api/tasks/{tid}/data", files=files, data=dict(image_quality=95, sorting_method="lexicographical"))
r.raise_for_status()
rq = r.json()["rq_id"]
for _ in range(300):
    st = s.get(f"{url}/api/requests/{rq}").json()
    if st["status"] in ("finished", "failed"):
        break
    time.sleep(1)
assert st["status"] == "finished", st
job = s.get(f"{url}/api/jobs", params=dict(task_id=tid)).json()["results"][0]
jid = job["id"]
labs = cv.labels(jid, tid)
LID = {l["name"]: l["id"] for l in labs}
SPEC = {(l["name"], a["name"]): a["id"] for l in labs for a in l.get("attributes", [])}
print(f"task {tid} job {jid}")

# ---- 2. nhan dung (box tu GT BDD + polygon SAM tu box) roi cai loi
sam = L.SamRefiner()


def attrs(label, **v):
    out = []
    for (ln, an), sid in SPEC.items():
        if ln == label:
            out.append(dict(spec_id=sid, value=str(v.get(an, "false"))))
    return out


def poly_of(mask):
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cs, key=cv2.contourArea)
    p = cv2.approxPolyDP(c, 1.0, True).reshape(-1, 2)
    return [float(v) for v in p.reshape(-1)]


shapes, tracks, tags, planted = [], [], [], {}
for fr, n in enumerate(names):
    g = json.load(open(os.path.join(IM, "gt", os.path.splitext(n)[0] + ".json"), encoding="utf-8"))
    img = cv2.imdecode(np.fromfile(os.path.join(IM, "images", n), np.uint8), cv2.IMREAD_COLOR)[:, :, ::-1].copy()
    H, W = img.shape[:2]
    bikes = [o["box"] for o in g["objects"] if o["cls"] in ("motorcycle", "bicycle")]
    objs = []
    for o in g["objects"]:
        lb = o["cls"]
        if lb == "person":
            lb = "rider" if R._on_two(o["box"], bikes) >= 0.25 else "pedestrian"
        objs.append(dict(label=lb, box=[float(v) for v in o["box"]]))
    big = [o for o in objs if min(o["box"][2] - o["box"][0], o["box"][3] - o["box"][1]) >= 30]
    masks, _ = sam.predict_boxes(img, [o["box"] for o in big]) if big else ([], [])
    for o, m in zip(big, masks):
        o["mask"] = m & np.pad(np.ones((1, 1), bool), 0)[0, 0] if False else m
    cars = sorted([o for o in big if o["label"] in ("car", "truck", "bus")], key=lambda o: -(o["box"][2] - o["box"][0]) * (o["box"][3] - o["box"][1]))
    k3 = np.ones((3, 3), np.uint8)
    for k, o in enumerate(objs):
        o["key"] = f"f{fr}o{k}"
        o["poly_mask"] = o.get("mask")
    # --- cai loi theo frame
    if fr == 0:
        m = cars[0]["mask"].astype(np.uint8)
        A = m.sum()
        while m.sum() > 0.75 * A:
            m = cv2.erode(m, k3)
        cars[0]["poly_mask"] = m.astype(bool); planted["E1_co_vien"] = (fr, cars[0]["key"], "sai_vien")
        rid = next((o for o in objs if o["label"] == "rider"), None)
        if rid:
            rid["label"] = "pedestrian"; planted["E2_rider_thanh_pedestrian"] = (fr, rid["key"], "sai_nhan")
    if fr == 1:
        o = cars[0]
        m = o["mask"].copy(); x1, y1, x2, y2 = o["box"]
        m[:, int(x2 - 0.35 * (x2 - x1)):] = False
        o["poly_mask"] = m; planted["E3_mat_phan"] = (fr, o["key"], "sai_vien")
        o = cars[1]; o["drop"] = True; planted["E4_thieu_xe"] = (fr, o["key"], "thieu")
    if fr == 2:
        o = cars[0]; o["as_track"] = True; planted["E5_dung_track"] = (fr, o["key"], "sai_kieu")
        o = cars[1]
        m = o["mask"].astype(np.uint8); A = m.sum()
        while m.sum() < 1.35 * A:
            m = cv2.dilate(m, k3)
        o["poly_mask"] = m.astype(bool); planted["E6_phinh"] = (fr, o["key"], "sai_vien")
    if fr == 3:
        o = cars[0]; o["bowtie"] = True; planted["E7_polygon_xoan"] = (fr, o["key"], "polygon_hong")
        o = cars[1]; o["box"] = [o["box"][0], o["box"][1], W + 40.0, o["box"][3]]; planted["E9_ra_ngoai_anh"] = (fr, o["key"], "ngoai_anh")
        if len(cars) > 2:
            o = cars[2]
            T = np.float32([[1, 0, 0.3 * (o["box"][2] - o["box"][0])], [0, 1, 0]])
            o["poly_mask"] = cv2.warpAffine(o["mask"].astype(np.uint8), T, (W, H), flags=cv2.INTER_NEAREST).astype(bool)
            planted["E10_lech"] = (fr, o["key"], "sai_vien")
    else:
        dk = json.load(open(os.path.join(IM, "dieu_kien.json"), encoding="utf-8")).get(n, {})
        tags.append(dict(frame=fr, label_id=LID["image_info"], group=0, source="manual",
                         attributes=attrs("image_info", weather=dk.get("weather", "clear"), scene=dk.get("scene", "city street"),
                                          timeofday=dk.get("timeofday", "daytime"))))
    if fr == 3:
        planted["E8_thieu_tag_anh"] = (fr, None, "thieu")
    for gi, o in enumerate(objs, 1):
        o["frame"] = fr
        if o.get("drop"):
            continue
        a = attrs(o["label"])
        rect = dict(type="rectangle", frame=fr, label_id=LID[o["label"]], points=o["box"], attributes=a,
                    group=gi if o.get("poly_mask") is not None else 0, occluded=False, source="manual", z_order=0, rotation=0)
        if o.get("as_track"):
            kf = {k: v for k, v in rect.items() if k not in ("label_id", "group", "source")}
            tracks.append(dict(frame=fr, label_id=LID[o["label"]], group=0, source="manual", attributes=a,
                               shapes=[dict(kf, outside=False, attributes=[]), dict(kf, frame=fr + 1, outside=True, attributes=[])]))
            o["is_track"] = True
        else:
            shapes.append(rect)
        if o.get("poly_mask") is not None and o["poly_mask"].any():
            p = poly_of(o["poly_mask"])
            if o.get("bowtie") and len(p) >= 8:
                p[2:4], p[len(p) // 2:len(p) // 2 + 2] = p[len(p) // 2:len(p) // 2 + 2], p[2:4]
            shapes.append(dict(type="polygon", frame=fr, label_id=LID[o["label"]], points=p, attributes=a, group=gi,
                               occluded=False, source="manual", z_order=0, rotation=0))
        o["frame"] = fr
    globals().setdefault("ALL", {}).update({o["key"]: o for o in objs})

r = s.put(f"{url}/api/jobs/{jid}/annotations", json=dict(version=0, shapes=shapes, tracks=tracks, tags=tags))
if not r.ok: print(r.text[:2000])
r.raise_for_status()
ann = cv.annotations(jid)
print(f"Da dua nhan: {len(ann['shapes'])} shape, {len(ann['tracks'])} track, {len(ann['tags'])} tag; cai {len(planted)} loi:",
      ", ".join(planted))


def ids_of(key):
    """id CVAT (shape / track) cua 1 vat da cai loi"""
    o = ALL[key]
    out = []
    for sh in ann["shapes"]:
        if sh["frame"] == o["frame"] and sh["label_id"] == LID[o["label"]] and sh["type"] == "rectangle" and \
                all(abs(a - b) < 0.5 for a, b in zip(sh["points"], o["box"])):
            out.append(f"shape {sh['id']}")
            g = sh["group"]
            out += [f"shape {x['id']}" for x in ann["shapes"] if x["type"] == "polygon" and x["group"] == g and g and x["frame"] == o["frame"]]
    for t in ann["tracks"]:
        k = t["shapes"][0]
        if k["frame"] == o["frame"] and all(abs(a - b) < 0.5 for a, b in zip(k["points"], o["box"])):
            out.append(f"track {t['id']}")
    return out


# ---- 3. guideline BDD100K + file luat, dat lam guideline mac dinh -> review qua worker (giong web)
gtext = G.extract_text(os.path.join(D, "guideline_bdd100k", "GUIDELINE_BDD100K.md"))
gid = store.add_guideline("BDD100K det + ins-seg", "GUIDELINE_BDD100K.md", "", gtext,
                          open(os.path.join(D, "guideline_bdd100k", "luat_bdd100k.yaml"), encoding="utf-8").read(), "e2e")
store.set_settings(default_guideline_id=gid)
w = Wm.Worker()


def review(tag):
    run_id = store.new_run(jid, tid, "e2e", dict(mode="chinh_xac"), store.task_guideline(tid), 2)
    t0 = time.time()
    w._run(run_id)
    print(f"\n==== {tag}: run {run_id} xong sau {time.time() - t0:.0f}s")
    for line in w.logs[run_id]:
        if any(k in line for k in ("Guideline", "theo guideline", "Kiểu nhãn", "polygon / mask", "Tầng 1", "Xong", "Khớp", "frame")):
            print("  " + line[:170])
    return run_id


run1 = review("VONG 1")
rv = w.review_obj(run1)
F = rv.findings
print(f"\n{len(F)} ghi chu ({sum(f['sure'] for f in F)} chac):")
for i, f in enumerate(F):
    print(f"  [{i:2d}] F{f['frame']} {'CHAC' if f['sure'] else 'kc  '} {f['kind']:15s} {str(f.get('ref')):12s} {f['msg'][:110]}")

print("\n== Bat duoc loi cai vao?")
caught = {}
for name, (fr, key, kind) in planted.items():
    refs = ids_of(key) if key else []
    hit = [f for f in F if f["frame"] == fr and (f.get("ref") in refs if refs else f["kind"] == kind and not f.get("ref"))]
    if name == "E4_thieu_xe":
        o = ALL[key]
        hit = [f for f in F if f["frame"] == fr and f["kind"] == "thieu" and R.L.iou(f["box"], o["box"]) >= 0.5]
    if name == "E8_thieu_tag_anh":
        hit = [f for f in F if f["frame"] == fr and ("image_info" in f["msg"] or "nhãn cho cả ảnh" in f["msg"].lower() or f["label"] == "image_info")]
    caught[name] = hit
    print(f"  {name:28s} {'BAT ' + ('chac' if any(h['sure'] for h in hit) else 'kc') if hit else 'BO LOT'}  "
          f"{hit[0]['msg'][:90] if hit else ''}")

# ---- 4. day Issue: moi loi chac + loi khong chac cua loi cai vao (nguoi review da xem va tick)
ids = [i for i, f in enumerate(F) if f["sure"] or any(f is h for v in caught.values() for h in v)]
res = w.push(run1, ids)
print(f"\nDay Issue vong 1: {res}")

# ---- 5. gia lap annotator sua mot phan + reviewer
ann = cv.annotations(jid)
sh = {x["id"]: x for x in ann["shapes"]}
fixed, upd = [], []


def fix_poly(key):
    o = ALL[key]
    for ref in ids_of(key):
        x = sh.get(int(ref.split()[1])) if ref.startswith("shape") else None
        if x and x["type"] == "polygon":
            x["points"] = poly_of(o["mask"])
            upd.append(x)
            return True


if fix_poly(planted["E1_co_vien"][1]): fixed.append("E1")
if fix_poly(planted["E3_mat_phan"][1]): fixed.append("E3")
for ref in ids_of(planted["E9_ra_ngoai_anh"][1]):
    x = sh[int(ref.split()[1])]
    if x["type"] == "rectangle":
        x["points"][2] = 1280.0; upd.append(x); fixed.append("E9")
o = ALL[planted["E4_thieu_xe"][1]]
new = [dict(type="rectangle", frame=o["frame"], label_id=LID[o["label"]], points=o["box"], attributes=attrs(o["label"]),
            group=0, occluded=False, source="manual", z_order=0, rotation=0)]
fixed.append("E4")
for t in ann["tracks"]:                       # track -> shape
    k = t["shapes"][0]
    new.append(dict(type="rectangle", frame=k["frame"], label_id=t["label_id"], points=k["points"], attributes=t["attributes"],
                    group=0, occluded=False, source="manual", z_order=0, rotation=0))
fixed.append("E5")
# PATCH tung shape nhu annotator sua that tren CVAT (id cua shape khong sua duoc giu nguyen)
for act, body in (("update", dict(shapes=upd, tracks=[], tags=[])), ("create", dict(shapes=new, tracks=[], tags=[])),
                  ("delete", dict(shapes=[], tracks=ann["tracks"], tags=[]))):
    r = s.patch(f"{url}/api/jobs/{jid}/annotations", params=dict(action=act), json=dict(version=0, **body))
    if not r.ok:
        print(act, r.status_code, r.text[:500])
    r.raise_for_status()
print(f"\nAnnotator sua: {fixed} (E2 rider, E6 phinh, E7 xoan, E10 lech, E8 tag: KHONG sua)")
# annotator dong Issue E2 ma khong sua (khong dong y) -> 'khong_sua'
e2refs = ids_of(planted["E2_rider_thanh_pedestrian"][1])
for it in cv.issues(jid):
    ti = R.tool_issue(cv.first_comment(it["id"]))
    if ti and ti[0] and any(fp.split("|", 2)[2] in e2refs for fp in ti[0].split(";")):
        cv.resolve_issue(it["id"]); print(f"  dong Issue {it['id']} (E2) ma khong sua")
# reviewer review cheo: tim them 1 loi tool khong bao -> tao Issue tay
cv.create_issue(jid, 0, [10, 10, 80, 80], "Reviewer: thiếu box traffic sign ở góc trái trên.")
# reviewer danh dau 1 ghi chu khong chac (khong phai loi cai) la "tool nham"
fpid = next((i for i, f in enumerate(F) if not f["sure"] and not any(f is h for v in caught.values() for h in v)), None)
if fpid is not None:
    store.set_feedback(run1, fpid, "tool_nham", "e2e", "e2e")
    print(f"  danh dau 'tool nham' ghi chu [{fpid}]")

# ---- 6. do hieu qua
e = w.effect([jid])
show = lambda e: {k: (round(v, 3) if isinstance(v, float) else v) for k, v in e.items() if k not in ("per_job", "theo_loai", "errors")}
print("\n== HIEU QUA sau vong 1:", show(e))
for k, v in e["theo_loai"].items():
    print(f"   {k:22s} {v}")
print("   loi:", e["errors"])

# ---- 7. vong 2: annotator nop lai -> review lai, Issue loi da het duoc dong
run2 = review("VONG 2")
res2 = w.push(run2, [i for i, f in enumerate(w.review_obj(run2).findings) if f["sure"]])
print(f"Day Issue vong 2: {res2}")
w.__dict__.pop("_effect_cache", None)
e = w.effect([jid])
print("\n== HIEU QUA sau vong 2:", show(e))
for j in e["per_job"]:
    print("   job", j)
json.dump(dict(task=tid, job=jid, planted=list(planted), caught={k: bool(v) for k, v in caught.items()}, effect=e),
          open(os.path.join(SP, "e2e_result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print(f"\nCVAT: {url}/tasks/{tid}/jobs/{jid}")
import hieu_qua
rs = store.list_runs(job_id=jid)
det = hieu_qua.job_effect(cv, jid, rs, {r["id"]: store.get_feedback(r["id"]) for r in rs})
print("\n== Tung Issue (ket qua do):")
for x in sorted(det["issues"], key=lambda x: (x["ket_qua"], x["frame"] or 0)):
    print(f"   {x['ket_qua']:10s} F{x['frame']} {x['kind']:15s} #{x['issue']} {x['msg'][:80]}")

# ban sao du lieu web co khoa ma hoa + token (da ma hoa): xoa sau khi test
shutil.rmtree(SHADOW, ignore_errors=True)
