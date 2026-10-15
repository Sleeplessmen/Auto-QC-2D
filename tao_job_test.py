"""Tao 1 task test tren CVAT tu 1 thu muc anh + annotations.xml (export 'CVAT for images 1.1').

    venv\\Scripts\\python cvat_2d\\tao_job_test.py <thu muc> --url http://localhost:8080 --token <token>

Nhan cua task lay tu phan <labels> trong annotations.xml. Sau khi tao xong, chon job do tren web QC de review.
"""
import argparse
import os
import sys
import time
import xml.etree.ElementTree as ET

import requests

IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def wait(s, url, rq):
    for _ in range(600):
        st = s.get(f"{url}/api/requests/{rq}").json()
        if st["status"] in ("finished", "failed"):
            return st
        time.sleep(1)
    raise RuntimeError("CVAT xu ly qua lau")


def labels_from_xml(path):
    out = []
    for lb in ET.parse(path).getroot().iter("label"):
        attrs = []
        for a in lb.iter("attribute"):
            vals = (a.findtext("values") or "").split()
            attrs.append(dict(name=a.findtext("name"), mutable=a.findtext("mutable") == "True",
                              input_type=a.findtext("input_type"), default_value=a.findtext("default_value") or "",
                              values=vals))
        d = dict(name=lb.findtext("name"), type=lb.findtext("type") or "any", attributes=attrs)
        if lb.findtext("color"):
            d["color"] = lb.findtext("color")
        out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--url", default=os.environ.get("CVAT_URL", "http://localhost:8080"))
    ap.add_argument("--token", default=os.environ.get("CVAT_TOKEN"))
    ap.add_argument("--name", default=None)
    a = ap.parse_args()
    if not a.token:
        sys.exit("Thieu --token (Personal Access Token tao o CVAT: Profile -> Security).")
    url = a.url.rstrip("/").removesuffix("/api")
    xml = os.path.join(a.folder, "annotations.xml")
    imgs = sorted(f for f in os.listdir(a.folder) if f.lower().endswith(IMG_EXT))
    if not imgs:
        sys.exit("Thu muc khong co anh.")

    s = requests.Session()
    s.headers["Authorization"] = f"{'Bearer' if '.' in a.token else 'Token'} {a.token}"
    me = s.get(f"{url}/api/users/self")
    me.raise_for_status()
    print("CVAT:", url, "- tai khoan", me.json()["username"])

    labels = labels_from_xml(xml) if os.path.exists(xml) else [dict(name="car", type="any", attributes=[])]
    r = s.post(f"{url}/api/tasks", json=dict(name=a.name or f"test web qc - {os.path.basename(os.path.abspath(a.folder))}",
                                             labels=labels))
    r.raise_for_status()
    tid = r.json()["id"]
    print(f"Tao task {tid}, nhan: {[l['name'] for l in labels]}")

    files = [(f"client_files[{i}]", (f, open(os.path.join(a.folder, f), "rb"))) for i, f in enumerate(imgs)]
    r = s.post(f"{url}/api/tasks/{tid}/data", files=files, data=dict(image_quality=95, sorting_method="lexicographical"))
    r.raise_for_status()
    st = wait(s, url, r.json()["rq_id"])
    print(f"Upload {len(imgs)} anh: {st['status']} {st.get('message') or ''}")
    if st["status"] != "finished":
        sys.exit(1)

    if os.path.exists(xml):
        r = s.post(f"{url}/api/tasks/{tid}/annotations", params=dict(format="CVAT 1.1"),
                   files=dict(annotation_file=open(xml, "rb")))
        r.raise_for_status()
        st = wait(s, url, r.json()["rq_id"])
        print(f"Import nhan: {st['status']} {st.get('message') or ''}")

    job = s.get(f"{url}/api/jobs", params=dict(task_id=tid)).json()["results"][0]
    ann = s.get(f"{url}/api/jobs/{job['id']}/annotations").json()
    print(f"Job {job['id']}: {len(ann['shapes'])} shape, {len(ann['tracks'])} track")
    print(f"Mo tren CVAT: {url}/tasks/{tid}/jobs/{job['id']}")
    print(f"Tren web QC: Review job -> chon ket noi CVAT nay -> Job {job['id']} -> Danh gia")


if __name__ == "__main__":
    main()
