"""Gán nhãn keypoint/skeleton: mặt 50 điểm, người 17 điểm (chuẩn VinFast), bàn tay 21 điểm/tay.

- Mặt 50 điểm: lông mày 0-9, sống mũi 10-13, mắt (trái ảnh) 14-21, mắt (phải ảnh) 22-29,
  môi ngoài 30-41, môi trong 42-49 — đúng thứ tự ảnh mẫu.
- Người 17 điểm (HumanPose-17 VinFast): 1 Nose, 2/3 Eye R/L, 4/5 Ear R/L, 6/7 Shoulder R/L, 8/9 Elbow R/L,
  10/11 Wrist R/L, 12/13 Hip R/L, 14/15 Knee R/L, 16/17 Ankle R/L — 18 cạnh.
  "Phải/Trái" tính theo KHUNG ẢNH (R = nửa phải ảnh), không theo giải phẫu người trong ảnh.
- Bàn tay 21 điểm: 0 cổ tay; ngón cái 1-4, trỏ 5-8, giữa 9-12, áp út 13-16, út 17-20 (gốc -> đầu ngón).

Điểm lấy từ MediaPipe (face/pose/hand landmarker), mỗi điểm có độ tin cậy/visible. Điểm bị che hoặc
model không chắc -> visible=False (CVAT: occluded), KHÔNG tự bịa vị trí.
python keypoints.py ẢNH OUT_PREFIX
"""
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

# Ban exe (PyInstaller): models/ nam canh file exe
MODELS = os.path.join(os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__)), "models")
UPSCALE_TO = 1600          # ảnh nhỏ được phóng lên chừng này px chiều ngang cho model bắt tốt hơn
CROP_SIZE = 256            # mặt/tay nhỏ: cắt vùng, phóng lên chừng này px rồi mới dò (model bắt tốt hơn nhiều)
HAND_WINDOWS = (0.18, 0.26)  # cửa sổ trượt dò tay, theo tỉ lệ chiều ngang ảnh
HAND_MIN_SCORE = 0.6
HAND_SAME_FRAC = 0.35      # 2 bàn tay có điểm trung bình cách nhau < 35% cỡ tay -> cùng 1 tay
VIS_MIN = 0.5              # visibility của pose dưới mức này -> đánh dấu bị che

# MediaPipe face mesh index cho 50 điểm (thứ tự như ảnh mẫu)
FACE50 = [70, 63, 105, 66, 107,            # 0-4  lông mày trái ảnh: ngoài -> trong
          336, 296, 334, 293, 300,          # 5-9  lông mày phải ảnh: trong -> ngoài
          168, 6, 197, 195,                 # 10-13 sống mũi: trên -> dưới
          33, 160, 159, 158, 133, 153, 145, 144,     # 14-21 mắt trái ảnh: khoé ngoài, mi trên, khoé trong, mi dưới
          362, 385, 386, 387, 263, 373, 374, 380,    # 22-29 mắt phải ảnh: khoé trong, mi trên, khoé ngoài, mi dưới
          61, 40, 37, 0, 267, 270, 291, 321, 314, 17, 84, 91,   # 30-41 môi ngoài
          78, 81, 13, 311, 308, 402, 14, 178]        # 42-49 môi trong
FACE_EDGES = ([(i, i + 1) for i in range(0, 4)] + [(i, i + 1) for i in range(5, 9)] + [(i, i + 1) for i in range(10, 13)]
              + [(14, 15), (15, 16), (16, 17), (17, 18), (18, 19), (19, 20), (20, 21), (21, 14)]
              + [(22, 23), (23, 24), (24, 25), (25, 26), (26, 27), (27, 28), (28, 29), (29, 22)]
              + [(i, i + 1) for i in range(30, 41)] + [(41, 30)]
              + [(i, i + 1) for i in range(42, 49)] + [(49, 42)])

# VinFast 17 -> MediaPipe pose index. R = nửa phải ảnh = bên TRÁI của người đối diện camera.
POSE17 = {1: 0, 2: 2, 3: 5, 4: 7, 5: 8, 6: 11, 7: 12, 8: 13, 9: 14, 10: 15, 11: 16,
          12: 23, 13: 24, 14: 25, 15: 26, 16: 27, 17: 28}
POSE17_NAMES = {1: "Nose", 2: "Right Eye (R)", 3: "Left Eye (L)", 4: "Right Ear (R)", 5: "Left Ear (L)",
                6: "Right Shoulder (R)", 7: "Left Shoulder (L)", 8: "Right Elbow (R)", 9: "Left Elbow (L)",
                10: "Right Wrist (R)", 11: "Left Wrist (L)", 12: "Right Hip (R)", 13: "Left Hip (L)",
                14: "Right Knee (R)", 15: "Left Knee (L)", 16: "Right Ankle (R)", 17: "Left Ankle (L)"}
POSE17_EDGES = [(1, 2), (1, 3), (2, 4), (3, 5), (4, 6), (5, 7), (6, 7), (6, 8), (8, 10), (7, 9), (9, 11),
                (6, 12), (7, 13), (12, 13), (12, 14), (14, 16), (13, 15), (15, 17)]

HAND_NAMES = ["wrist", "thumb_cmc", "thumb_mcp", "thumb_ip", "thumb_tip", "index_mcp", "index_pip", "index_dip",
              "index_tip", "middle_mcp", "middle_pip", "middle_dip", "middle_tip", "ring_mcp", "ring_pip",
              "ring_dip", "ring_tip", "pinky_mcp", "pinky_pip", "pinky_dip", "pinky_tip"]
HAND_EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12),
              (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20)]


def _run_crop(landmarker, img, box, kind):
    """Dò trên 1 vùng cắt (phóng lên CROP_SIZE), trả tọa độ về ảnh gốc."""
    import mediapipe as mp
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.size[0], x1), min(img.size[1], y1)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return []
    c = img.crop((x0, y0, x1, y1))
    k = CROP_SIZE / c.size[0]
    cb = np.ascontiguousarray(np.asarray(c.resize((CROP_SIZE, max(8, round(c.size[1] * k))), Image.BICUBIC)))
    r = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cb))
    lms_list = r.face_landmarks if kind == "face" else r.hand_landmarks
    scores = [1.0] * len(lms_list) if kind == "face" else [h[0].score for h in r.handedness]
    out = []
    for lms, sc in zip(lms_list, scores):
        pts = [[round(x0 + lm.x * cb.shape[1] / k, 1), round(y0 + lm.y * cb.shape[0] / k, 1)] for lm in lms]
        out.append((pts, float(sc)))
    return out


def detect(path, kinds=("face", "person", "hand")):
    """kinds: chi do cac loai nay (do tay quet nhieu cua so -> cham, bo khi khong can)."""
    import mediapipe as mp
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision

    img = Image.open(path).convert("RGB")
    W, H = img.size
    k = max(1.0, UPSCALE_TO / W)
    big = np.ascontiguousarray(np.asarray(img.resize((round(W * k), round(H * k)), Image.BICUBIC)))
    mimg = mp.Image(image_format=mp.ImageFormat.SRGB, data=big)
    bw, bh = big.shape[1], big.shape[0]

    def to_px(lm):
        return [round(lm.x * bw / k, 1), round(lm.y * bh / k, 1)]

    out = dict(image=os.path.basename(path), width=W, height=H, faces=[], persons=[], hands=[])

    face_pts = []
    if "face" in kinds:
        face = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=mpt.BaseOptions(model_asset_path=os.path.join(MODELS, "face_landmarker.task")), num_faces=5))
        face_pts = [[to_px(lm) for lm in lms] for lms in face.detect(mimg).face_landmarks]

    pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=os.path.join(MODELS, "pose_landmarker_heavy.task")), num_poses=3))
    pose_res = pose.detect(mimg).pose_landmarks
    if "face" in kinds and not face_pts:
        # mặt nhỏ: cắt vùng quanh đầu (mũi, mắt, tai của pose) rồi dò lại
        for lms in pose_res:
            head = np.array([to_px(lms[j]) for j in (0, 2, 5, 7, 8)])
            cx, cy = head.mean(axis=0)
            half = max(20.0, 1.6 * float(np.ptp(head[:, 0])))
            for pts, _ in _run_crop(face, img, (cx - half, cy - half * 1.1, cx + half, cy + half * 0.9), "face"):
                face_pts.append(pts)
    for fp in face_pts:
        pts = [dict(id=i, xy=fp[j], visible=True) for i, j in enumerate(FACE50)]
        out["faces"].append(dict(label="face", points=pts, edges=FACE_EDGES))

    for lms in (pose_res if "person" in kinds else []):
        pts = []
        for vid, j in POSE17.items():
            v = float(getattr(lms[j], "visibility", 1.0) or 0.0)
            pts.append(dict(id=vid, name=POSE17_NAMES[vid], xy=to_px(lms[j]), visible=v >= VIS_MIN, score=round(v, 2)))
        out["persons"].append(dict(label="person", points=pts, edges=POSE17_EDGES))

    if "hand" not in kinds:
        return out
    hand = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=os.path.join(MODELS, "hand_landmarker.task")), num_hands=10,
        min_hand_detection_confidence=0.1, min_hand_presence_confidence=0.1))
    # Tay nhỏ: quét cửa sổ trượt nhiều cỡ, mỗi cửa sổ phóng lên rồi dò; gộp các lần dò trùng 1 bàn tay
    cands = []
    for frac in HAND_WINDOWS:
        win = frac * W
        step = win / 2
        for y0 in np.arange(0, max(1, H - win * 0.5), step):
            for x0 in np.arange(0, max(1, W - win * 0.5), step):
                for pts, sc in _run_crop(hand, img, (x0, y0, x0 + win, y0 + win), "hand"):
                    if sc >= HAND_MIN_SCORE:
                        cands.append((sc, np.array(pts)))
    # Tay của người chính: cắt quanh cổ tay (pose) — khớp khung với tay tốt hơn cửa sổ trượt
    for lms in pose_res:
        for wi, ei in ((15, 13), (16, 11 + 3)):
            wrist, elbow = np.array(to_px(lms[wi])), np.array(to_px(lms[ei]))
            fore = max(10.0, float(np.linalg.norm(wrist - elbow)))
            for f in (0.8, 1.1, 1.4):
                half = f * fore
                for pts, sc in _run_crop(hand, img, (wrist[0] - half, wrist[1] - half * 1.3, wrist[0] + half,
                                                     wrist[1] + half * 0.7), "hand"):
                    if sc >= HAND_MIN_SCORE:
                        cands.append((sc + 0.05, np.array(pts)))   # ưu tiên nhẹ tay gắn với người
    cands.sort(key=lambda c: -c[0])
    kept = []
    for sc, pts in cands:
        size = float(np.ptp(pts, axis=0).max())
        if any(np.linalg.norm(pts - k, axis=1).mean() < HAND_SAME_FRAC * max(size, 1.0) for _, k in kept):
            continue
        kept.append((sc, pts))
    for sc, pts in kept:
        side = "R" if pts[0][0] >= W / 2 else "L"     # R/L theo nửa khung ảnh (quy ước của tài liệu)
        p = [dict(id=i, name=HAND_NAMES[i], xy=[float(v) for v in pts[i]], visible=True) for i in range(21)]
        out["hands"].append(dict(label=f"hand ({side})", score=round(sc, 2), points=p, edges=HAND_EDGES))
    return out


def draw(path, data, out_path, scale=3):
    im = np.asarray(Image.open(path).convert("RGB"))[:, :, ::-1]
    vis = cv2.resize(im, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    groups = [(data["faces"], (255, 0, 255), 1, 0.3), (data["persons"], (0, 255, 0), 0, 0.4),
              (data["hands"], (0, 200, 255), 0, 0.3)]
    for objs, col, off, fs in groups:
        for o in objs:
            p = {pt["id"]: pt for pt in o["points"]}
            for a, b in o["edges"]:
                if a in p and b in p:
                    pa = tuple(int(v * scale) for v in p[a]["xy"])
                    pb = tuple(int(v * scale) for v in p[b]["xy"])
                    cv2.line(vis, pa, pb, col, 1)
            for pt in o["points"]:
                c = tuple(int(v * scale) for v in pt["xy"])
                cv2.circle(vis, c, 3, col if pt["visible"] else (128, 128, 128), -1)
                cv2.putText(vis, str(pt["id"]), (c[0] + 3, c[1] - 3), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), 1)
    cv2.imwrite(out_path, vis)


if __name__ == "__main__":
    src, prefix = sys.argv[1], sys.argv[2]
    data = detect(src)
    json.dump(data, open(prefix + "_keypoints.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    draw(src, data, prefix + "_keypoints.jpg")
    print(f"mặt: {len(data['faces'])}  người: {len(data['persons'])}  bàn tay: {len(data['hands'])}")
    for pers in data["persons"]:
        print("  pose điểm bị che:", [p["id"] for p in pers["points"] if not p["visible"]])
