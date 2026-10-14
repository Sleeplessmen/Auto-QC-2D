import os
import tempfile
import argparse
from dotenv import load_dotenv
from cvat_client import CvatClient
import keypoints

PART_RANGES = {
    "longmaytrai": range(0, 5),
    "longmayphai": range(5, 10),
    "songmui": range(10, 14),
    "mattrai": range(14, 22),
    "matphai": range(22, 30),
    "moingoai": range(30, 42),
    "moitrong": range(42, 50),
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=int)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--env", type=str, default=".env", help="Đường dẫn đến file cấu hình (.env, .env.class, ...)")
    args = parser.parse_args()

    load_dotenv(args.env)
    client = CvatClient(os.environ["CVAT_URL"], os.environ["CVAT_TOKEN"])
    job_id = int(os.environ["CVAT_JOB_ID"])
    
    schema = client.get_label_schema(job_id)
    print(f"Loaded schema with {len(schema)} labels.")
    
    meta = client.get_job_meta(job_id)
    start_frame, stop_frame = meta["start_frame"], meta["stop_frame"]
    frames = [args.frame] if args.frame is not None else list(range(start_frame, stop_frame + 1))
    
    for frame_number in frames:
        print(f"[frame {frame_number}] Tải ảnh...")
        image = client.get_frame_image(job_id, frame_number)
        
        # Lưu ảnh tạm để keypoints.py có thể đọc
        fd, temp_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        image.save(temp_path)
        
        try:
            print(f"[frame {frame_number}] Nhận diện keypoints...")
            data = keypoints.detect(temp_path)
            
            shapes = []
            
            for face in data["faces"]:
                # Tính bounding box cho face
                pts = [p["xy"] for p in face["points"]]
                if pts and "face" in schema:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    xtl, ytl, xbr, ybr = min(xs), min(ys), max(xs), max(ys)
                    # Nới rộng ra một chút
                    xtl, ytl = max(0, xtl - 10), max(0, ytl - 10)
                    xbr, ybr = min(image.width, xbr + 10), min(image.height, ybr + 10)
                    shapes.append({
                        "type": "rectangle",
                        "occluded": False,
                        "z_order": 0,
                        "points": [xtl, ytl, xbr, ybr],
                        "frame": frame_number,
                        "label_id": schema["face"]["id"],
                        "group": 0,
                        "source": "manual",
                        "attributes": []
                    })
                
                # Tạo skeleton cho từng phần
                for part_name, part_range in PART_RANGES.items():
                    if part_name not in schema:
                        continue
                        
                    elements = []
                    for pid in part_range:
                        # Tìm điểm trong kết quả
                        point = next((p for p in face["points"] if p["id"] == pid), None)
                        if not point:
                            continue
                            
                        sub_name = str(pid)
                        if sub_name not in schema[part_name]["sublabels"]:
                            continue
                            
                        elements.append({
                            "type": "points",
                            "frame": frame_number,
                            "label_id": schema[part_name]["sublabels"][sub_name],
                            "points": point["xy"],
                            "occluded": not point["visible"],
                            "outside": False,
                            "source": "manual"
                        })
                    
                    if elements:
                        shapes.append({
                            "type": "skeleton",
                            "occluded": False,
                            "frame": frame_number,
                            "label_id": schema[part_name]["id"],
                            "group": 0,
                            "source": "manual",
                            "elements": elements
                        })

            if args.push and shapes:
                client.push_annotations(job_id, shapes)
                print(f"[frame {frame_number}] ✅ Đã đẩy {len(shapes)} shape (bao gồm skeleton) lên CVAT.")
            else:
                print(f"[frame {frame_number}] Nhận diện {len(shapes)} shape (dry-run).")
                
        finally:
            os.remove(temp_path)

if __name__ == "__main__":
    main()
