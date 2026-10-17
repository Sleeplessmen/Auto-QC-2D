"""Test job VIDEO dung Track tren CVAT (ket noi so 2 cua web QC, mac dinh CVAT localhost).
6 khung lien tiep (cung 1 canh BDD), moi vat gan bang Track, guideline "dung Track". Cai 3 loi:
  T1 polygon track ve lem o keyframe 3 (khung noi suy 1, 2, 4 khong duoc bao oan)
  T2 1 xe bi tach thanh 2 track noi tiep (dut track)
  T3 track nhay sang xe khac o khung 1
    venv\\Scripts\\python cvat_2d\\kiem_thu\\test_e2e_track.py      (ket qua: kiem_thu/ket_qua/e2e_track.json)"""
import json, os, shutil, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.dirname(HERE)
DATA = os.path.join(D, "du_lieu_danh_gia")                         # trong repo (cvat_2d/du_lieu_danh_gia)
if not os.path.isdir(DATA):
    DATA = os.path.join(os.path.dirname(D), "du_lieu_danh_gia")
SP = os.path.join(HERE, "ket_qua")
os.makedirs(SP, exist_ok=True)
sys.path.insert(0, D); sys.path.insert(0, os.path.join(D, "web_qc")); os.chdir(D)
for f in (sys.stdout, sys.stderr):
    f.reconfigure(encoding="utf-8")

import store
SHADOW = os.path.join(SP, "track_data")
shutil.rmtree(SHADOW, ignore_errors=True)
shutil.copytree(store.DATA, SHADOW, ignore=shutil.ignore_patterns("uploads"))
store.DATA, store.DB_PATH = SHADOW, os.path.join(SHADOW, "web_qc.db")
store.init()
store.set_settings(auto_validation=False, webhook_enabled=False)

import cv2, numpy as np
import review_core as R, label_hq_2d as L, guideline as G
import worker as Wm

conn = store.get_connection(2)
cv = R.Cvat(conn["url"], conn["token"])
url = conn["url"].rstrip("/")
s = cv.s
IM = os.path.join(DATA, "bdd_e2e")
NAME = "b27098c3-c443b6e3"
NF = 6
labels_def = json.load(open(os.path.join(D, "guideline_bdd100k", "labels_bdd100k.json"), encoding="utf-8"))

# ---- task 6 khung (anh lap lai = canh dung yen)
tmp = tempfile.mkdtemp()
for i in range(NF):
    shutil.copy(os.path.join(IM, "images", NAME + ".jpg"), os.path.join(tmp, f"frame_{i:03d}.jpg"))
r = s.post(f"{url}/api/tasks", json=dict(name=f"e2e video track {time.strftime('%H%M%S')}", labels=labels_def))
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


def kf(frame, typ, pts, outside=False):
    return dict(type=typ, frame=frame, points=[float(v) for v in pts], outside=outside, occluded=False, z_order=0,
                rotation=0, attributes=[])


def poly_of(mask):
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return [float(v) for v in cv2.approxPolyDP(max(cs, key=cv2.contourArea), 1.0, True).reshape(-1)]


g = json.load(open(os.path.join(IM, "gt", NAME + ".json"), encoding="utf-8"))
img = cv2.imdecode(np.fromfile(os.path.join(IM, "images", NAME + ".jpg"), np.uint8), cv2.IMREAD_COLOR)[:, :, ::-1].copy()
bikes = [o["box"] for o in g["objects"] if o["cls"] in ("motorcycle", "bicycle")]
objs = []
for o in g["objects"]:
    lb = o["cls"]
    if lb == "person":
        lb = "rider" if R._on_two(o["box"], bikes) >= 0.25 else "pedestrian"
    objs.append(dict(label=lb, box=[float(v) for v in o["box"]]))
cars = sorted([o for o in objs if o["label"] in ("car", "truck", "bus")], key=lambda o: -(o["box"][2] - o["box"][0]) * (o["box"][3] - o["box"][1]))
A, B, C, C2 = cars[0], cars[1], cars[2], cars[3]
sam = L.SamRefiner()
mA = sam.predict_boxes(img, [A["box"]])[0][0]
m = mA.astype(np.uint8)
area0 = m.sum()
while m.sum() > 0.72 * area0:
    m = cv2.erode(m, np.ones((3, 3), np.uint8))
tracks = []
for o in objs:
    if o is B or o is C:
        continue
    tracks.append(dict(frame=0, label_id=LID[o["label"]], group=0, source="manual", attributes=attrs(o["label"]),
                       shapes=[kf(0, "rectangle", o["box"])]))
# T1: polygon track cua xe A: keyframe 0, 5 dung; keyframe 3 ve lem
tracks.append(dict(frame=0, label_id=LID[A["label"]], group=0, source="manual", attributes=attrs(A["label"]),
                   shapes=[kf(0, "polygon", poly_of(mA)), kf(3, "polygon", poly_of(m.astype(bool))), kf(5, "polygon", poly_of(mA))]))
# T2: xe B tach thanh 2 track: khung 0-2 va 3-5
tracks.append(dict(frame=0, label_id=LID[B["label"]], group=0, source="manual", attributes=attrs(B["label"]),
                   shapes=[kf(0, "rectangle", B["box"]), kf(3, "rectangle", B["box"], outside=True)]))
tracks.append(dict(frame=3, label_id=LID[B["label"]], group=0, source="manual", attributes=attrs(B["label"]),
                   shapes=[kf(3, "rectangle", B["box"])]))
# T3: track xe C o khung 0, khung 1 nhay sang xe C2 (o xa), roi quay lai C
tracks.append(dict(frame=0, label_id=LID[C["label"]], group=0, source="manual", attributes=attrs(C["label"]),
                   shapes=[kf(0, "rectangle", C["box"]), kf(1, "rectangle", C2["box"]), kf(2, "rectangle", C["box"])]))
r = s.put(f"{url}/api/jobs/{jid}/annotations", json=dict(version=0, shapes=[], tracks=tracks, tags=[]))
if not r.ok:
    print(r.text[:800])
r.raise_for_status()
ann = cv.annotations(jid)
print(f"Da dua nhan: {len(ann['tracks'])} track, {len(ann['shapes'])} shape")
tA = next(t for t in ann["tracks"] if any(k["type"] == "polygon" for k in t["shapes"]))["id"]
tB2 = next(t for t in ann["tracks"] if t["frame"] == 3 if t["shapes"][0]["frame"] == 3)["id"]
tC = next(t for t in ann["tracks"] if len(t["shapes"]) == 3 and t["shapes"][0]["type"] == "rectangle")["id"]

# ---- guideline video: dung Track (gan rieng cho task nay)
rules = open(os.path.join(D, "guideline_bdd100k", "luat_bdd100k.yaml"), encoding="utf-8").read().replace("kieu_nhan: shape", "kieu_nhan: track")
gid = store.add_guideline("Video test (Track)", "video.md", "", "2. Video: gán bằng Track, nối vật qua các khung.", rules, "e2e")
store.set_task_guideline(tid, gid)
w = Wm.Worker()
run_id = store.new_run(jid, tid, "e2e", dict(mode="chinh_xac"), store.task_guideline(tid), 2)
w._run(run_id)
for line in w.logs[run_id]:
    if any(k in line for k in ("Guideline", "Kiểu nhãn", "Track:", "polygon / mask", "frame", "Xong")):
        print("  " + line[:170])
F = w.review_obj(run_id).findings
print(f"\n{len(F)} ghi chu:")
for f in F:
    if f["kind"] in ("sai_vien", "track", "sai_kieu", "polygon_hong") or str(f.get("ref", "")).startswith("track"):
        print(f"  F{f['frame']} {'CHAC' if f['sure'] else 'kc  '} {f['kind']:10s} {str(f.get('ref')):10s} {f['msg'][:120]}")
res = {
    "T1 lem o keyframe 3": any(f["frame"] == 3 and f["kind"] == "sai_vien" and f["ref"] == f"track {tA}" for f in F),
    "T1 khung noi suy khong bao oan (1,2,4)": not any(f["frame"] in (1, 2, 4) and f["ref"] == f"track {tA}" for f in F),
    "T1 xe A khong bi bao 'thieu' o khung noi suy": not any(f["kind"] == "thieu" and f["frame"] in (1, 2, 4) and L.iou(f["box"], A["box"]) >= 0.5 for f in F),
    "T2 dut track (1 vat 2 ID)": any(f["kind"] == "track" and f["ref"] == f"track {tB2}" and ("đứt" in f["msg"] or f.get("sub") == "mot_vat_2_id")
                                     for f in F),
    "T3 nhay vi tri": any(f["kind"] == "track" and f["ref"] == f"track {tC}" and "nhảy" in f["msg"] for f in F),
    "Khong bao 'can Shape' (guideline dung Track)": not any(f["kind"] == "sai_kieu" for f in F),
}
print("\n== KET QUA")
for k, v in res.items():
    print(f"  {'DAT ' if v else 'HONG'} {k}")
json.dump(dict(task=tid, job=jid, ket_qua=res), open(os.path.join(SP, "e2e_track.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\nCVAT: {url}/tasks/{tid}/jobs/{jid}")
shutil.rmtree(SHADOW, ignore_errors=True)
shutil.rmtree(tmp, ignore_errors=True)
