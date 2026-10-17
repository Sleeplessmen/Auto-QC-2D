"""
label_check.py — Kiểm tra annotation 3D cuboid trên CVAT trước khi nộp.

Bắt các lỗi hay gặp khi vẽ tay:
  - SAI NHÃN: kích thước không khớp tên nhãn (vd box ô tô 4.4x2.0m mà nhãn "Animal" — CVAT
    luôn chọn sẵn nhãn đầu danh sách khi vẽ box mới, quên đổi là sai).
  - LƠ LỬNG / CHÌM: đáy box cách mặt đất > 0.6m (lỡ tay vẽ trên không).
  - RỖNG: gần như không có điểm lidar trong box.
  - TRÙNG: 2 box gần như cùng chỗ.

Tên nhãn được nhận theo nghĩa (vehicles/car/truck/bus..., two-wheels/motorcycle/bicycle...,
pedestrian/person, animal/dog...) nên dùng được cho task có bộ nhãn khác. Nhãn không nhận ra
(vd "Obstacle") thì không kiểm tra kích thước.

Cách dùng (kiemtra.bat = lệnh tắt):
  kiemtra 10866                 # 1 job
  kiemtra 10846-10866           # dải job
  kiemtra --task 2885           # cả task
  kiemtra --task 2885 --fix     # tự đổi nhãn cho box SAI NHÃN rõ ràng (sao lưu trước); lỗi khác chỉ báo
"""
import argparse
import copy
import json
import os
import re
import sys
import time

import numpy as np

# Loai vat theo ten nhan (so khop sau khi bo hoa thuong / ky tu dac biet)
KIND_WORDS = [
    ("vehicle", ("vehicle", "car", "truck", "bus", "van", "trailer", "oto", "xeoto")),
    ("two-wheels", ("twowheel", "motor", "bicycle", "bike", "scooter", "xemay")),
    ("pedestrian", ("pedestrian", "person", "human", "nguoi")),
    ("animal", ("animal", "dog", "cat", "cow", "convat")),
]
FLOAT_TOL = 0.6      # m: day box lech mat dat qua muc nay -> lo lung / chim
MIN_POINTS = 5       # it hon -> box rong


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def label_kind(name):
    n = norm(name)
    for kind, words in KIND_WORDS:
        if any(w in n for w in words):
            return kind
    return None


def size_kind(L, W, H):
    """Loai vat suy tu kich thuoc (chi tra ve khi ro rang, khong thi None)."""
    big, small = max(L, W), min(L, W)
    if big >= 3.0 and small >= 1.4:
        return "vehicle"
    if big <= 1.2 and small <= 1.2 and H >= 1.0:
        return "pedestrian-or-small"
    return None


def wrong_label(name, L, W, H):
    """-> (loai dung, ly do) neu nhan chac chan sai, nguoc lai None."""
    lk, sk = label_kind(name), size_kind(L, W, H)
    if lk in ("two-wheels", "pedestrian", "animal") and sk == "vehicle":
        return "vehicle", f"kich thuoc o to {L:.1f}x{W:.1f}x{H:.1f}m ma nhan '{name}'"
    if lk == "vehicle" and sk == "pedestrian-or-small":
        return None, f"nhan '{name}' ma box chi {L:.1f}x{W:.1f}x{H:.1f}m"
    return None


def find_label(labels, kind):
    """Ten nhan cua job ung voi loai vat (vd 'vehicle' -> 'vehicles' hoac 'car')."""
    names = [n for n in labels if label_kind(n) == kind]
    if not names:
        return None
    pref = [n for n in names if norm(n) in ("vehicles", "vehicle", "car")]
    return (pref or names)[0]


# Lop chi tiet -> (tu khoa ten nhan rieng, nhom chung). Thu tu tu khoa quan trong: "motorbike" truoc "bike".
CLASSES = {
    "car": (("car", "oto", "sedan", "suv"), "vehicle"),
    "truck": (("truck", "xetai", "lorry"), "vehicle"),
    "bus": (("bus", "xebuyt", "coach"), "vehicle"),
    "motorcycle": (("motorcycle", "motorbike", "motor", "scooter", "xemay"), "two-wheels"),
    "bicycle": (("bicycle", "xedap"), "two-wheels"),
    "pedestrian": (("pedestrian", "person", "human", "nguoi"), "pedestrian"),
    "animal": (("animal", "dog", "cat", "cow", "convat"), "animal"),
}


def pick_label(labels, cls):
    """Chon ten nhan CO TRONG JOB cho lop vat cls.
    Uu tien nhan rieng (task co 'truck' thi xe tai -> 'truck'), khong co thi nhan nhom
    (task chi co 'vehicles' -> 'vehicles'). Khong khop gi -> None (khong doan bua)."""
    words, group = CLASSES[cls]
    for n in labels:
        nn = norm(n)
        if cls == "bicycle" and "motor" in nn:
            continue
        if any(nn == w or nn == w + "s" for w in words):
            return n
    for n in labels:
        nn = norm(n)
        if cls == "car" and ("scar" in nn or "carg" in nn):     # tranh "oscar", "cargo"
            continue
        if any(w in nn for w in words) and label_kind(n) == group:
            return n
    return find_label(labels, group)


def class_of(name, L, W, H):
    """Lop chi tiet cua 1 box tu ten nhan + kich thuoc (kich thuoc thang neu nhan ro rang sai)."""
    lk = label_kind(name)
    wl = wrong_label(name, L, W, H)
    if wl and wl[0]:
        lk = wl[0]
    if lk == "vehicle":
        n = norm(name)
        for c in ("bus", "truck", "car"):
            if any(w in n for w in CLASSES[c][0]):
                return c
        big = max(L, W)
        return "bus" if big >= 8.5 else "truck" if (big >= 6.0 or H >= 2.5) else "car"
    if lk == "two-wheels":
        return "bicycle" if any(w in norm(name) for w in CLASSES["bicycle"][0]) and "motor" not in norm(name) \
            else "motorcycle"
    return lk     # pedestrian / animal / None


def fix_labels(boxes, labels, log, where=lambda b: f"({b['x']:.1f},{b['y']:.1f})"):
    """Kiem tra lan cuoi truoc khi day: nhan phai co trong job va khop kich thuoc.
    Box khong tim duoc nhan phu hop -> bo (tra ve danh sach con lai)."""
    out = []
    for b in boxes:
        name = b["label"]
        wl = wrong_label(name, b["L"], b["W"], b["H"])
        if name in labels and not wl:
            out.append(b)
            continue
        cls = class_of(name, b["L"], b["W"], b["H"])
        new = pick_label(labels, cls) if cls else None
        if new:
            log(f"  Doi nhan {where(b)}: '{name}' -> '{new}'"
                + (f" ({wl[1]})" if wl else " (job khong co nhan nay)"))
            b["label"] = new
            out.append(b)
        elif wl and name in labels:
            log(f"  CAN XEM {where(b)}: {wl[1]} -> giu nguyen, sua tay")
            out.append(b)
        else:
            log(f"  BO {where(b)}: '{name}' khong co nhan phu hop trong job {sorted(labels)}")
    return out


def check_job(client, job_id, load_job, in_footprint):
    """Tra ve (job dict, danh sach loi). Moi loi: dict(kind, shape, msg, fix_label)."""
    job = load_job(client, job_id)
    labels = client.get_label_schema(job_id)
    inv = {v: k for k, v in labels.items()}
    pts, ground = job["pts"], job["ground"]
    issues = []
    boxes = []
    for s in job["shapes"]:
        x, y, z, rx, ry, rz, L, W, H = s["points"][:9]
        name = inv.get(s["label_id"], str(s["label_id"]))
        where = f"{name} ({x:.1f},{y:.1f})"
        wl = wrong_label(name, L, W, H)
        if wl:
            kind, why = wl
            issues.append(dict(kind="SAI NHAN", shape=s, msg=f"{where}: {why}",
                               fix_label=find_label(labels, kind) if kind else None))
        gz = float(ground.height(np.array([x]), np.array([y]))[0])
        bottom = z - H / 2 - gz
        if abs(bottom) > FLOAT_TOL:
            issues.append(dict(kind="LO LUNG" if bottom > 0 else "CHIM", shape=s, fix_label=None,
                               msg=f"{where}: day box {'cao' if bottom > 0 else 'thap'} hon mat dat {abs(bottom):.1f}m"))
        inside = in_footprint(pts[:, :2], x, y, rz, L, W) & (pts[:, 2] > z - H / 2) & (pts[:, 2] < z + H / 2)
        if inside.sum() < MIN_POINTS:
            issues.append(dict(kind="RONG", shape=s, fix_label=None,
                               msg=f"{where}: chi {int(inside.sum())} diem lidar trong box"))
        for (bx, by, bn, bs) in boxes:
            if np.hypot(bx - x, by - y) < 0.5:
                issues.append(dict(kind="TRUNG", shape=s, fix_label=None,
                                   msg=f"{where}: trung cho voi box {bn} ({bx:.1f},{by:.1f})"))
        boxes.append((x, y, name, s))
    return job, labels, issues


def parse_jobs(client, spec, task, request):
    if task:
        r = request(client.sess, "GET", f"{client.base_url}/api/jobs",
                    params={"task_id": task, "page_size": 500}).json()
        return [j["id"] for j in sorted(r["results"], key=lambda j: j["start_frame"])]
    out = []
    for part in spec:
        if "-" in part:
            a, b = map(int, part.split("-"))
            out += list(range(a, b + 1))
        else:
            out.append(int(part))
    return out


def main():
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass
    here = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Kiem tra annotation 3D truoc khi nop")
    ap.add_argument("jobs", nargs="*", help="Job hoac dai job, vd 10866 hoac 10846-10866")
    ap.add_argument("--task", type=int, help="Kiem tra ca task")
    ap.add_argument("--fix", action="store_true", help="Tu doi nhan cho box SAI NHAN ro rang (sao luu truoc)")
    ap.add_argument("--env", default=os.path.join(here, ".env"))
    args = ap.parse_args()
    if not args.jobs and not args.task:
        ap.error("can job (vd 10866, 10846-10866) hoac --task")
    os.chdir(here)
    sys.path.insert(0, here)
    from dotenv import load_dotenv
    load_dotenv(args.env, override=True)
    try:
        from auto_annotate_3d import CvatClient3D, _request_with_retry
        from auto_annotate_seq import load_job, in_footprint
    except ImportError:
        sys.exit("label_check.py là công cụ cho job 3D: cần auto_annotate_3d.py và auto_annotate_seq.py của bộ tool 3D "
                 "(thư mục cvat_3d), chép vào cạnh file này. Repo cvat_2d chỉ có phần 2D.")

    client = CvatClient3D(os.environ["CVAT_URL"], os.environ["CVAT_TOKEN"])
    jobs = parse_jobs(client, args.jobs, args.task, _request_with_retry)
    total, fixed = 0, 0
    for jid in jobs:
        job, labels, issues = check_job(client, jid, load_job, in_footprint)
        total += len(issues)
        if not issues:
            print(f"job {jid}: OK ({len(job['shapes'])} box)")
            continue
        print(f"job {jid}: {len(issues)} loi / {len(job['shapes'])} box")
        for it in issues:
            hint = f"  -> --fix doi thanh '{it['fix_label']}'" if it["fix_label"] else ""
            print(f"   [{it['kind']}] {it['msg']}{hint}")
        todo = [it for it in issues if it["kind"] == "SAI NHAN" and it["fix_label"]]
        if args.fix and todo:
            os.makedirs("backup_3d", exist_ok=True)
            bk = os.path.join("backup_3d", f"job{jid}_truoc_kiemtra_{time.strftime('%Y%m%d_%H%M%S')}.json")
            json.dump({"shapes": job["shapes"], "tracks": job["tracks"]}, open(bk, "w", encoding="utf-8"),
                      ensure_ascii=False)
            upd = []
            for it in todo:
                s = copy.deepcopy(it["shape"])
                s["label_id"] = labels[it["fix_label"]]
                s["attributes"] = []
                upd.append(s)
            client._patch(jid, upd, [], "update")
            fixed += len(upd)
            print(f"   Da doi nhan {len(upd)} box (sao luu {bk})")
    print(f"\nTong: {total} loi tren {len(jobs)} job" + (f", da sua {fixed} box sai nhan" if args.fix else ""))
    if total and not args.fix:
        print("SAI NHAN ro rang: chay lai voi --fix de tu doi. Loi khac (lo lung, rong, trung): sua tay tren CVAT.")


if __name__ == "__main__":
    main()
