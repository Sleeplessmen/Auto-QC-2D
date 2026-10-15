"""Tai truoc moi model tool can (chay 1 lan, can Internet). Goi tu cai_dat.bat.

- SAM2.1 large  -> ../checkpoints/sam2.1_hiera_large.pt
- YOLO11x, RT-DETR-x, YOLOv8x-seg -> thu muc nay
- D-FINE-X, CLIP ViT-L/14, SegFormer-b5 Cityscapes -> cache HuggingFace
"""
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SAM_URL = "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt"


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
