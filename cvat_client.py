"""
CVAT API client — cung cấp class CvatClient để auto_annotate.py gọi.
Chạy trực tiếp file này để kiểm tra kết nối và xem danh sách label của job.
"""
import io
import os
import sys
from dotenv import load_dotenv
import requests
from PIL import Image


class CvatClient:
    """Wrapper gọi CVAT REST API v2."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        # CVAT dùng "Token xxx" cho session token (hex), "Bearer xxx" cho API key (có dấu chấm)
        prefix = "Bearer" if "." in token else "Token"
        self.session.headers.update({"Authorization": f"{prefix} {token}"})

    # ------------------------------------------------------------------
    # Job / Task metadata
    # ------------------------------------------------------------------

    def get_job_meta(self, job_id: int) -> dict:
        """Trả về dict chứa start_frame, stop_frame, size của job."""
        r = self.session.get(f"{self.base_url}/api/jobs/{job_id}")
        r.raise_for_status()
        data = r.json()
        start = data.get("start_frame", 0)
        stop = data.get("stop_frame", 0)
        return {
            "start_frame": start,
            "stop_frame": stop,
            "size": stop - start + 1,
        }

    def get_all_jobs(self) -> list[int]:
        """Trả về danh sách tất cả job_id thuộc task (lấy từ CVAT_TASK_ID trong env)."""
        task_id = int(os.environ.get("CVAT_TASK_ID", 0))
        r = self.session.get(f"{self.base_url}/api/jobs", params={"task_id": task_id, "page_size": 500})
        r.raise_for_status()
        return [j["id"] for j in r.json().get("results", [])]

    # ------------------------------------------------------------------
    # Label schema
    # ------------------------------------------------------------------

    def get_label_schema(self, job_id: int) -> dict:
        """Trả về dict {label_name: {"id": int, "attributes": {attr_name: spec_id},
        "attr_values": {attr_name: [giá trị hợp lệ]}}}."""
        r = self.session.get(
            f"{self.base_url}/api/labels",
            params={"job_id": job_id, "page_size": 200},
        )
        r.raise_for_status()
        schema = {}
        for lb in r.json().get("results", []):
            attrs, values = {}, {}
            for spec in lb.get("attributes", []):
                attrs[spec["name"]] = spec["id"]
                values[spec["name"]] = list(spec.get("values", []))
            
            sublabels = {}
            for sub in lb.get("sublabels", []):
                sublabels[sub["name"]] = sub["id"]

            schema[lb["name"]] = {
                "id": lb["id"], 
                "attributes": attrs, 
                "attr_values": values,
                "sublabels": sublabels
            }
        return schema

    # ------------------------------------------------------------------
    # Frame image
    # ------------------------------------------------------------------

    def get_frame_image(self, job_id: int, frame_number: int) -> Image.Image:
        """Tải ảnh của frame (số thứ tự trong job) từ CVAT, trả về PIL.Image."""
        r = self.session.get(
            f"{self.base_url}/api/jobs/{job_id}/data",
            params={"type": "frame", "number": frame_number, "quality": "original"},
            stream=True,
        )
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")

    # ------------------------------------------------------------------
    # Push annotations
    # ------------------------------------------------------------------

    def push_annotations(self, job_id: int, shapes: list) -> None:
        """Đẩy danh sách shape lên CVAT (action=create — không xoá annotation cũ)."""
        payload = {
            "version": 0,
            "tags": [],
            "shapes": shapes,
            "tracks": [],
        }
        r = self.session.patch(
            f"{self.base_url}/api/jobs/{job_id}/annotations",
            json=payload,
            params={"action": "create"},
        )
        r.raise_for_status()

    # ------------------------------------------------------------------
    # Delete annotations
    # ------------------------------------------------------------------

    def delete_auto_annotations(self, job_id: int) -> int:
        """Xoá tất cả shape có source='auto' hoặc 'semi-auto' trong job. Trả về số shape đã xoá."""
        existing = self._get_all_shapes(job_id)
        to_delete = [s for s in existing if s.get("source") in ("auto", "semi-auto")]
        if to_delete:
            self._delete_shapes_by_id(job_id, to_delete)
        return len(to_delete)

    def delete_all_annotations(self, job_id: int) -> int:
        """Xoá TOÀN BỘ annotation (mọi source) trong job. Trả về số shape đã xoá."""
        existing = self._get_all_shapes(job_id)
        count = len(existing)
        r = self.session.delete(f"{self.base_url}/api/jobs/{job_id}/annotations")
        r.raise_for_status()
        return count

    def get_shapes_for_frame(self, job_id: int, frame_number: int) -> list:
        """Trả về danh sách shape đầy đủ field thuộc đúng 1 frame trong job."""
        return [s for s in self._get_all_shapes(job_id) if s.get("frame") == frame_number]

    def delete_shapes(self, job_id: int, shapes: list[dict]) -> None:
        """Xoá đúng các shape (không đụng tới shape khác trong job).

        `shapes` phải là các dict shape ĐẦY ĐỦ (như trả về từ get_shapes_for_frame /
        _get_all_shapes) — CVAT yêu cầu đủ field (type, frame, label_id, ...) ngay cả khi
        action=delete, chỉ truyền mỗi "id" sẽ bị 400 Bad Request.
        """
        self._delete_shapes_by_id(job_id, shapes)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_all_shapes(self, job_id: int) -> list:
        r = self.session.get(f"{self.base_url}/api/jobs/{job_id}/annotations")
        r.raise_for_status()
        return r.json().get("shapes", [])

    def _delete_shapes_by_id(self, job_id: int, shapes: list[dict]) -> None:
        """Xoá đúng các shape (full dict, xem delete_shapes) bằng PATCH action=delete."""
        if not shapes:
            return
        payload = {
            "version": 0,
            "tags": [],
            "tracks": [],
            "shapes": shapes,
        }
        r = self.session.patch(
            f"{self.base_url}/api/jobs/{job_id}/annotations",
            json=payload,
            params={"action": "delete"},
        )
        r.raise_for_status()


# ------------------------------------------------------------------
# Chạy trực tiếp để kiểm tra kết nối
# ------------------------------------------------------------------
if __name__ == "__main__":
    load_dotenv(override=True)
    url = os.environ["CVAT_URL"]
    token = os.environ["CVAT_TOKEN"]
    job_id = int(os.environ["CVAT_JOB_ID"])
    task_id = int(os.environ["CVAT_TASK_ID"])

    client = CvatClient(url, token)

    meta = client.get_job_meta(job_id)
    print(f"Job {job_id} | Task {task_id}")
    print(f"  Frame: {meta['start_frame']} → {meta['stop_frame']} ({meta['size']} ảnh)")

    schema = client.get_label_schema(job_id)
    print(f"\nLabels trong task ({len(schema)} nhãn):")
    for name, info in sorted(schema.items()):
        print(f"  id={info['id']:<5} name={name}")
