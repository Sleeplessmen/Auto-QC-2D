"""Test LOI ID cua track tren CVAT (ket noi so 2 cua web QC, mac dinh CVAT localhost).
Video 8 khung co vat chuyen dong (cat dich dan 1 anh BDD dong xe, nhu camera lia ngang 20px / khung). Cai 5 loi ID:
  S1 trao ID: 2 xe sat nhau, track K va J tra vat cho nhau o khung 4
  S2 doi vat: track M theo xe R, toi khung 4 chuyen sang xe S ben canh (xe R van con)
  S3 1 vat 2 ID: xe U co track A (khung 0-1) va track B (khung 5-7)
  S4 2 ID 1 vat: 2 track cung nam tren xe V
  S5 ket thuc som: track xe X het o khung 3, xe van con
  S6 kich thuoc khong dong bo: track xe W o khung 3-4 box thap di 35% (cac khung khac dung)
Cac track dung con lai: khong duoc bao loi ID.
    venv\\Scripts\\python cvat_2d\\kiem_thu\\test_e2e_id.py      (ket qua: kiem_thu/ket_qua/e2e_id.json)"""
import json, os, shutil, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.dirname(HERE)
DATA = os.path.join(os.path.dirname(D), "du_lieu_danh_gia")
SP = os.path.join(HERE, "ket_qua")
os.makedirs(SP, exist_ok=True)
sys.path.insert(0, D); sys.path.insert(0, os.path.join(D, "web_qc")); os.chdir(D)
for f in (sys.stdout, sys.stderr):
    f.reconfigure(encoding="utf-8")

import store
SHADOW = os.path.join(SP, "id_data")
shutil.rmtree(SHADOW, ignore_errors=True)
shutil.copytree(store.DATA, SHADOW, ignore=shutil.ignore_patterns("uploads"))
store.DATA, store.DB_PATH = SHADOW, os.path.join(SHADOW, "web_qc.db")
store.init()
store.set_settings(auto_validation=False, webhook_enabled=False)

import cv2, numpy as np
import review_core as R, label_hq_2d as L
import worker as Wm

conn = store.get_connection(2)
cv = R.Cvat(conn["url"], conn["token"])
url = conn["url"].rstrip("/")
s = cv.s
IM = os.path.join(DATA, "bdd_e2e")
NAME = "c323201c-9bcf7cf8"
NF, STEP, CW = 8, 20, 1120
labels_def = json.load(open(os.path.join(D, "guideline_bdd100k", "labels_bdd100k.json"), encoding="utf-8"))

img = cv2.imdecode(np.fromfile(os.path.join(IM, "images", NAME + ".jpg"), np.uint8), cv2.IMREAD_COLOR)
H = img.shape[0]
tmp = tempfile.mkdtemp()
for k in range(NF):
    ok, buf = cv2.imencode(".jpg", img[:, k * STEP:k * STEP + CW], [cv2.IMWRITE_JPEG_QUALITY, 95])
    buf.tofile(os.path.join(tmp, f"frame_{k:03d}.jpg"))


def at(box, k):
    """box cua vat o khung k (anh dich trai STEP px moi khung); None neu ra ngoai"""
    x1, y1, x2, y2 = box[0] - k * STEP, box[1], box[2] - k * STEP, box[3]
    x1, x2 = max(0.0, x1), min(float(CW), x2)
    return [x1, y1, x2, y2] if x2 - x1 > 8 else None


r = s.post(f"{url}/api/tasks", json=dict(name=f"e2e loi ID track {time.strftime('%H%M%S')}", labels=labels_def))
r.raise_for_status()
tid = r.json()["id"]
files = [(f"client_files[{i}]", (f"frame_{i:03d}.jpg", open(os.path.join(tmp, f"frame_{i:03d}.jpg"), "rb"))) for i in range(NF)]
r = s.post(f"{url}/api/tasks/{tid}/data", files=files, data=dict(image_quality=95, sorting_method="lexicographical"))
r.raise_for_status()
rq = r.json()["rq_id"]
for _ in range(300):
    st = s.get(f"{url}/api/requests/{rq}").json()
    if st["status"] in ("finished", "failed"):
        break
    time.sleep(1)
assert st["status"] == "finished", st
jid = s.get(f"{url}/api/jobs", params=dict(task_id=tid)).json()["results"][0]["id"]
labs = cv.labels(jid, tid)
LID = {l["name"]: l["id"] for l in labs}
SPEC = {(l["name"], a["name"]): a["id"] for l in labs for a in l.get("attributes", [])}
print(f"task {tid} job {jid}")


def attrs(label):
    return [dict(spec_id=sid, value="false") for (ln, an), sid in SPEC.items() if ln == label and an in ("occluded", "truncated")]


g = json.load(open(os.path.join(IM, "gt", NAME + ".json"), encoding="utf-8"))
bikes = [o["box"] for o in g["objects"] if o["cls"] in ("motorcycle", "bicycle")]
objs = []
for o in g["objects"]:
    lb = o["cls"]
    if lb == "person":
        lb = "rider" if R._on_two(o["box"], bikes) >= 0.25 else "pedestrian"
    if all(at(o["box"], k) for k in range(NF)):          # chi lay vat con trong anh ca 8 khung
        objs.append(dict(label=lb, box=[float(v) for v in o["box"]]))
veh = sorted([o for o in objs if o["label"] in ("car", "truck", "bus") and min(o["box"][2] - o["box"][0], o["box"][3] - o["box"][1]) >= 40],
             key=lambda o: -(o["box"][2] - o["box"][0]) * (o["box"][3] - o["box"][1]))


def closest_pair(pool):
    best = None
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            a, b = pool[i]["box"], pool[j]["box"]
            if pool[i]["label"] != pool[j]["label"]:
                continue
            d = abs((a[0] + a[2]) / 2 - (b[0] + b[2]) / 2) + abs((a[1] + a[3]) / 2 - (b[1] + b[3]) / 2)
            if best is None or d < best[0]:
                best = (d, pool[i], pool[j])
    return best[1], best[2]


pool = list(veh)
P, Q = closest_pair(pool); pool = [o for o in pool if o is not P and o is not Q]
Rr, Sx = closest_pair(pool); pool = [o for o in pool if o is not Rr and o is not Sx]
U, V, X, W = pool[0], pool[1], pool[2], pool[3]
print("xe dung de cai loi:", len(veh), "xe lon; cap tráo:", P["box"][:2], Q["box"][:2])


def track(label, boxes_by_frame, outside_after=None):
    """boxes_by_frame: {k: box}; keyframe moi khung co box; outside_after: them keyframe outside"""
    ks = [dict(type="rectangle", frame=k, points=b, outside=False, occluded=False, z_order=0, rotation=0, attributes=[])
          for k, b in sorted(boxes_by_frame.items())]
    if outside_after is not None:
        ks.append(dict(type="rectangle", frame=outside_after, points=boxes_by_frame[max(boxes_by_frame)], outside=True,
                       occluded=False, z_order=0, rotation=0, attributes=[]))
    return dict(frame=min(boxes_by_frame), label_id=LID[label], group=0, source="manual", attributes=attrs(label), shapes=ks)


full = lambda o: {k: at(o["box"], k) for k in range(NF)}
tracks, planted = [], {}
special = {id(o) for o in (P, Q, Rr, Sx, U, V, X, W)}
for o in objs:                                               # vat binh thuong: 1 track dung suot 8 khung
    if id(o) not in special:
        tracks.append(track(o["label"], full(o)))
tracks.append(track(P["label"], {k: at((P if k < 4 else Q)["box"], k) for k in range(NF)}))   # K
tracks.append(track(Q["label"], {k: at((Q if k < 4 else P)["box"], k) for k in range(NF)}))   # J
tracks.append(track(Rr["label"], {k: at((Rr if k < 4 else Sx)["box"], k) for k in range(NF)}))  # M (R khong con track nao khac)
tracks.append(track(U["label"], {k: at(U["box"], k) for k in (0, 1)}, outside_after=2))       # A
tracks.append(track(U["label"], {k: at(U["box"], k) for k in (5, 6, 7)}))                     # B
tracks.append(track(V["label"], full(V)))                                                       # V1
shr = lambda b: [b[0] + 0.12 * (b[2] - b[0]), b[1] + 0.12 * (b[3] - b[1]), b[2] - 0.02 * (b[2] - b[0]), b[3] - 0.02 * (b[3] - b[1])]
tracks.append(track(V["label"], {k: shr(at(V["box"], k)) for k in range(NF)}))                 # V2
tracks.append(track(X["label"], {k: at(X["box"], k) for k in range(4)}, outside_after=4))      # X ket thuc som
low = lambda b: [b[0], b[1] + 0.35 * (b[3] - b[1]), b[2], b[3]]
tracks.append(track(W["label"], {k: (low(at(W["box"], k)) if k in (3, 4) else at(W["box"], k)) for k in range(NF)}))  # W
r = s.put(f"{url}/api/jobs/{jid}/annotations", json=dict(version=0, shapes=[], tracks=tracks, tags=[]))
if not r.ok:
    print(r.text[:800])
r.raise_for_status()
ann = cv.annotations(jid)
T = sorted(ann["tracks"], key=lambda t: t["id"])
n_norm = len(T) - 9
ids = {nm: f"track {T[n_norm + i]['id']}" for i, nm in enumerate(["K", "J", "M", "A", "B", "V1", "V2", "X", "W"])}
normal = {f"track {t['id']}" for t in T[:n_norm]}
print(f"Da dua nhan: {len(T)} track ({n_norm} track dung)")

rules = open(os.path.join(D, "guideline_bdd100k", "luat_bdd100k.yaml"), encoding="utf-8").read().replace("kieu_nhan: shape", "kieu_nhan: track")
gid = store.add_guideline("Video test (Track)", "video.md", "", "2. Video: gán bằng Track, nối vật qua các khung.", rules, "e2e")
store.set_task_guideline(tid, gid)
w = Wm.Worker()
run_id = store.new_run(jid, tid, "e2e", dict(mode="chinh_xac"), store.task_guideline(tid), 2)
t0 = time.time()
w._run(run_id)
print(f"review xong sau {time.time() - t0:.0f}s")
for line in w.logs[run_id]:
    if any(k in line for k in ("track", "Track", "ID")):
        print("  " + line[:170])
F = w.review_obj(run_id).findings
idf = [f for f in F if f["kind"] == "track"]
print(f"\nGhi chu ve track / ID ({len(idf)}):")
for f in idf:
    print(f"  F{f['frame']} {'CHAC' if f['sure'] else 'kc  '} {str(f.get('sub')):13s} {f['ref']:10s} {f['msg'][:130]}")
has = lambda sub, *refs: any(f.get("sub") == sub and f["ref"] in [ids[r] for r in refs] for f in F)
res = {
    "S1 tráo ID (K/J)": has("trao_id", "K", "J"),
    "S2 đổi vật (M)": has("doi_vat", "M"),
    "S3 1 vật 2 ID (B)": has("mot_vat_2_id", "B"),
    "S4 2 ID 1 vật (V1/V2)": has("hai_id_1_vat", "V1", "V2"),
    "S5 track kết thúc sớm (X)": has("ket_thuc_som", "X"),
    "S6 kích thước không đồng bộ (W, khung 3-4)": any(f.get("sub") == "kich_thuoc" and f["ref"] == ids["W"] and 3 in f.get("frames", [])
                                                     for f in F),
    "Track đúng không bị báo lỗi ID / kích thước": not any(
        f.get("sub") in ("doi_vat", "trao_id", "mot_vat_2_id", "hai_id_1_vat", "ket_thuc_som", "kich_thuoc", "kich_thuoc_nhay")
        and f["ref"] in normal for f in F),
}
thieu = [f for f in F if f["kind"] == "thieu"]
print(f"\nGhi chu 'thieu': {len(thieu)}")
for f in thieu:
    print(f"  F{f['frame']} {'CHAC' if f['sure'] else 'kc  '} {f['msg'][:120]}")
print("\nGhi chu tren track W (kich thuoc):")
for f in F:
    if f["ref"] == ids["W"]:
        print(f"  F{f['frame']} {'CHAC' if f['sure'] else 'kc  '} {f['kind']:14s} {str(f.get('sub')):12s} {f['msg'][:120]}")
print("  W khop vat tool:", w.review_obj(run_id).idc.debug_seq.get(ids["W"]))
print("\n== KET QUA")
for k, v in res.items():
    print(f"  {'DAT ' if v else 'HONG'} {k}")
json.dump(dict(task=tid, job=jid, ket_qua=res), open(os.path.join(SP, "e2e_id.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\nCVAT: {url}/tasks/{tid}/jobs/{jid}")
shutil.rmtree(SHADOW, ignore_errors=True)
shutil.rmtree(tmp, ignore_errors=True)
