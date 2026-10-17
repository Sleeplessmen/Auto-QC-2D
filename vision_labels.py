"""
vision_labels.py — Nhìn ảnh camera để biết VẬT LÀ GÌ, theo đúng bộ nhãn của từng job.

  1. Đọc danh sách nhãn của job trên CVAT -> mỗi nhãn có vài "từ mô tả" (prompt) tiếng Anh.
     Lấy từ file labels/task<id>.json nếu có (người dùng tự sửa được), không có thì tự tạo:
       vehicles -> car, taxi, van, suv, pickup truck, truck, bus ; two-wheels -> motorcycle, scooter, bicycle
       pedestrian -> person ; Animal -> dog, cat, cow, chicken ; nhãn lạ -> chính tên nhãn ("traffic_light" -> "traffic light")
  2. YOLOE (mô hình nhận diện theo chữ, không cần huấn luyện) tìm các vật đó trên từng ảnh camera,
     khoanh đường viền (mask).
  3. Chiếu điểm lidar lên ảnh (calib/task<id>.json) -> điểm lidar thuộc vật -> 1 vật 3D có nhãn.
     Cùng 1 vật thấy ở 2 camera -> gộp lại. Người ngồi trên xe máy -> gộp vào xe máy.

Dùng trong auto_annotate_seq.py: đổi nhãn box lidar khi camera nói khác rõ ràng, và thêm vật camera
thấy mà lidar-heuristic bỏ sót.
"""
import json
import os
import re
import sys

import numpy as np

from label_check import label_kind, norm

# Ban exe (PyInstaller): du lieu nam canh file exe
HERE = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROMPTS = {
    "vehicle": ["car", "taxi", "van", "suv", "pickup truck", "truck", "bus"],
    "two-wheels": ["motorcycle", "scooter", "bicycle"],
    "pedestrian": ["person"],
    "animal": ["dog", "cat", "cow", "chicken"],
}
SPECIFIC = {   # nhan rieng (task kieu nuScenes) -> prompt rieng
    "car": ["car", "taxi", "suv", "van"], "truck": ["truck", "pickup truck"], "bus": ["bus"],
    "motorcycle": ["motorcycle", "scooter"], "bicycle": ["bicycle"], "trailer": ["trailer"],
    "obstacle": ["traffic cone", "road barrier", "bollard"], "barrier": ["road barrier", "fence barrier"],
    "trafficcone": ["traffic cone"], "constructionvehicle": ["excavator", "construction vehicle"],
}
MIN_PTS = {"vehicle": 25, "two-wheels": 12, "pedestrian": 8, "animal": 6, None: 10}


def labels_path(task_id):
    return os.path.join(HERE, "labels", f"task{task_id}.json")


def make_prompts(label_names):
    """{ten nhan: [prompt...]} tu dong theo nghia ten nhan."""
    out = {}
    for name in label_names:
        n = norm(name)
        if n in SPECIFIC:
            out[name] = SPECIFIC[n]
        elif n.rstrip("s") in SPECIFIC:
            out[name] = SPECIFIC[n.rstrip("s")]
        elif label_kind(name) in DEFAULT_PROMPTS:
            out[name] = DEFAULT_PROMPTS[label_kind(name)]
        else:
            out[name] = [re.sub(r"[_\-/]+", " ", name).strip().lower()]
    return out


def load_prompts(task_id, label_names):
    """File labels/task<id>.json (sua tay duoc). Chua co -> tao tu dong va luu lai de nguoi dung sua."""
    p = labels_path(task_id)
    auto = make_prompts(label_names)
    if os.path.exists(p):
        cfg = json.load(open(p, encoding="utf-8"))
        prompts = {k: v for k, v in cfg.get("prompts", {}).items() if k in label_names}
        for k in label_names:                        # nhan moi them vao task -> bo sung tu dong
            prompts.setdefault(k, auto[k])
    else:
        prompts = auto
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump({"_huong_dan": "Moi nhan CVAT -> cac tu tieng Anh mo ta vat (YOLOE tim theo chu). "
                                 "Sua/them tu cho dung dinh nghia nhan cua du an. Nhan khong muon tu gan: de [].",
                   "prompts": prompts}, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return prompts


class VisionLabeler:
    def __init__(self, task_id, label_names, calib, model="yoloe-11l-seg.pt", conf=0.3, log=print):
        from ultralytics import YOLOE
        import torch
        self.device = 0 if torch.cuda.is_available() else "cpu"
        self.calib = {k: v for k, v in calib.items() if v.get("use", True)}
        self.prompts = load_prompts(task_id, label_names)
        self.texts, self.text_label = [], []
        for lab, ws in self.prompts.items():
            for w in ws:
                if w not in self.texts:
                    self.texts.append(w)
                    self.text_label.append(lab)
        if not self.texts:
            raise ValueError("Khong co prompt nao")
        self.model = YOLOE(os.path.join(HERE, model) if os.path.exists(os.path.join(HERE, model)) else model)
        self.model.set_classes(self.texts, self.model.get_text_pe(self.texts))
        self.conf = conf
        log(f"  Camera: {len(self.calib)} camera dung duoc, {len(self.texts)} tu mo ta cho {len(self.prompts)} nhan"
            f" ({'GPU' if self.device == 0 else 'CPU - cham'})")

    def detect(self, images):
        """{cam: anh RGB} -> {cam: dict(size=(W,H), dets=[(mask bool 1/2 do phan giai, nhan, conf)])}"""
        out = {}
        for cam, im in images.items():
            if cam not in self.calib:
                continue
            r = self.model.predict(np.ascontiguousarray(im[:, :, ::-1]), conf=self.conf, verbose=False,
                                   imgsz=1280, device=self.device, retina_masks=True)[0]
            dets = []
            if r.masks is not None:
                masks = r.masks.data.cpu().numpy()[:, ::2, ::2] > 0.5
                for m, c, s in zip(masks, r.boxes.cls.cpu().numpy(), r.boxes.conf.cpu().numpy()):
                    dets.append((m, self.text_label[int(c)], float(s)))
            out[cam] = dict(size=(im.shape[1], im.shape[0]), dets=dets)
        return out

    def objects(self, job, images, not_ego, dets=None, min_pts_scale=1.0):
        """Vat 3D tu camera: list dict(label, conf, idx (chi so diem lidar), cams). dets: ket qua detect() da co."""
        return camera_objects(job, dets if dets is not None else self.detect(images), self.calib, not_ego,
                              min_pts_scale)


# Kich thuoc 3D toi thieu cua phan vat nhin thay (cao, ngang) va do cao day toi da so voi mat dat
OBJ_MIN = {"vehicle": (0.7, 0.9), "two-wheels": (0.6, 0.4), "pedestrian": (0.8, 0.2), "animal": (0.2, 0.2), None: (0.3, 0.3)}
OBJ_MAX_H = {"vehicle": 4.0, "two-wheels": 2.3, "pedestrian": 2.2, "animal": 1.8, None: 4.0}


def camera_objects(job, dets, calib, not_ego, min_pts_scale=1.0):
    try:
        from camera_calib import project          # bo tool 3D (thu muc cvat_3d), khong co trong repo cvat_2d
    except ImportError as e:
        raise RuntimeError("camera_objects can camera_calib.py cua bo tool 3D (thu muc cvat_3d)") from e
    from sklearn.cluster import DBSCAN
    pts, h = job["pts"], job["h"]
    r = np.hypot(pts[:, 0], pts[:, 1])
    cand = np.where((h > 0.1) & (h < 4.5) & (r < 60) & (r > 1.0) & not_ego(pts))[0]
    objs = []
    for cam, d in dets.items():
        if cam not in calib or not d["dets"]:
            continue
        W, H = d["size"]
        u, v, z, ok = project(calib[cam], pts[cand], (W, H))
        ci, ui, vi, zi = cand[ok], (u[ok] / 2).astype(int), (v[ok] / 2).astype(int), z[ok]
        for m, lab, s in d["dets"]:
            inm = m[np.minimum(vi, m.shape[0] - 1), np.minimum(ui, m.shape[1] - 1)]
            if inm.sum() < 3:
                continue
            idx, zz = ci[inm], zi[inm]
            grp = label_kind(lab)
            mh, mw = OBJ_MIN.get(grp, OBJ_MIN[None])
            if min_pts_scale < 0.5:                 # lidar thua: vat chi co vai vong quet -> noi nguong kich thuoc
                mh, mw = mh * 0.4, mw * 0.5
            lab_c = DBSCAN(eps=0.7, min_samples=3).fit_predict(pts[idx])
            best = None
            for l in set(lab_c) - {-1}:
                k = lab_c == l
                P, hk = pts[idx[k]], h[idx[k]]
                # Vat that: cham dat, du cao, du rong (than cay / cot mo phia truoc vat bi che -> loai)
                tall = float(hk.max() - min(hk.min(), 0.3))
                wide = float(max(np.ptp(P[:, 0]), np.ptp(P[:, 1])))
                if hk.min() > 0.8 or tall < mh or wide < mw or hk.max() > OBJ_MAX_H.get(grp, 4.0) + 0.5:
                    continue
                if grp == "pedestrian" and wide > 1.3:     # nguoi ma dai > 1.3m -> nguoi lai xe
                    continue
                cnt, dep = int(k.sum()), float(np.median(zz[k]))
                if best is None or dep < best[1] - 1.0 or (cnt > 3 * best[0] and dep < best[1] + 3.0):
                    best = (cnt, dep, idx[k])
            if best is None or best[0] < max(3, MIN_PTS.get(grp, 10) * min_pts_scale):
                continue
            objs.append(dict(label=lab, conf=s, idx=set(best[2].tolist()), cams=[cam]))
    # gop cung 1 vat (2 camera / nguoi tren xe may)
    objs.sort(key=lambda o: -len(o["idx"]))
    merged = []
    for o in objs:
        for g in merged:
            if o["cams"][0] in g["cams"] and                     {label_kind(o["label"]), label_kind(g["label"])} != {"pedestrian", "two-wheels"}:
                continue        # 2 mask cung 1 anh = 2 vat khac nhau (tru nguoi lai + xe hai banh: gop)
            inter = len(o["idx"] & g["idx"])
            if inter >= 0.3 * min(len(o["idx"]), len(g["idx"])):
                g["idx"] |= o["idx"]
                g["votes"].append((o["label"], o["conf"], len(o["idx"])))
                g["cams"] += o["cams"]
                break
        else:
            merged.append(dict(o, votes=[(o["label"], o["conf"], len(o["idx"]))]))
    for g in merged:
        score = {}
        for lab, c, n in g["votes"]:
            score[lab] = score.get(lab, 0) + c * n
        kinds = {label_kind(l) for l in score}
        if "two-wheels" in kinds and "pedestrian" in kinds:      # nguoi lai xe -> xe hai banh
            score = {l: w for l, w in score.items() if label_kind(l) != "pedestrian"}
        g["label"] = max(score, key=score.get)
        g["conf"] = max(c for lab, c, n in g["votes"] if lab == g["label"])
        g["agree"] = score[g["label"]] / sum(c * n for _, c, n in g["votes"])
        g["idx"] = np.array(sorted(g["idx"]))
    return merged
