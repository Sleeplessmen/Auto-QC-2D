"""Tai truoc moi model tool can (chay 1 lan, can Internet). Goi tu cai_dat.bat.

- SAM2.1 large  -> ../checkpoints/sam2.1_hiera_large.pt
- YOLO11x, RT-DETR-x, YOLOv8x-seg -> thu muc nay
- D-FINE-X, CLIP ViT-L/14, SegFormer-b5 Cityscapes -> cache HuggingFace
- models/: MediaPipe face / hand / pose landmarker (keypoints.py), YOLOP (lane_markings.py) — tool gan nhan,
  web QC khong can
"""
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SAM_URL = "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt"
# tool gan nhan diem (keypoints.py) va vach ke duong (lane_markings.py); ultralytics khong tu tai cac file nay
MODEL_FILES = {
    "face_landmarker.task": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    "hand_landmarker.task": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
    "pose_landmarker_heavy.task": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task",
    "yolop-640-640.onnx": "https://github.com/hustvl/YOLOP/raw/main/weights/yolop-640-640.onnx",
}


def step(msg):
    print(f"\n== {msg}", flush=True)


def main():
    ckpt = os.path.join(ROOT, "checkpoints", "sam2.1_hiera_large.pt")
    step("SAM2.1 large")
    if os.path.exists(ckpt):
        print("  da co")
    else:
        os.makedirs(os.path.dirname(ckpt), exist_ok=True)
        urllib.request.urlretrieve(SAM_URL, ckpt + ".tmp",
                                   lambda b, s, t: print(f"\r  {b * s / 1e6:.0f}/{t / 1e6:.0f} MB", end="", flush=True))
        os.replace(ckpt + ".tmp", ckpt)
        print()

    for name, url in MODEL_FILES.items():
        dst = os.path.join(HERE, "models", name)
        step(f"models/{name}")
        if os.path.exists(dst):
            print("  da co")
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        urllib.request.urlretrieve(url, dst + ".tmp")
        os.replace(dst + ".tmp", dst)
        print(f"  {os.path.getsize(dst) / 1e6:.0f} MB")

    os.chdir(HERE)            # ultralytics tai file .pt vao thu muc hien tai
    from ultralytics import RTDETR, YOLO
    for name, cls in (("yolo11x.pt", YOLO), ("rtdetr-x.pt", RTDETR), ("yolov8x-seg.pt", YOLO)):
        step(name)
        cls(name)

    from transformers import (AutoImageProcessor, CLIPModel, CLIPProcessor, DFineForObjectDetection,
                              SegformerForSemanticSegmentation, SegformerImageProcessor)
    sys.path.insert(0, HERE)
    import area_check
    for name, parts in (("ustc-community/dfine-xlarge-obj2coco", (AutoImageProcessor, DFineForObjectDetection)),
                        ("openai/clip-vit-large-patch14", (CLIPProcessor, CLIPModel)),
                        (area_check.SEG_MODEL, (SegformerImageProcessor, SegformerForSemanticSegmentation))):
        step(name)
        for p in parts:
            p.from_pretrained(name)
    print("\nXong: da tai du model.")


if __name__ == "__main__":
    main()
