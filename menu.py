"""
menu.py — Menu gán nhãn CVAT, chọn theo KIỂU VẼ giống các nút "Draw new ..." trên CVAT.

Bấm đúp menu.bat (hoặc gõ `menu` / `menu 10842` / `menu 55 --env .env.class` trong terminal ở thư mục này).
  0. Có nhiều file cấu hình (.env, .env.class ...) -> chọn file (bỏ qua nếu đã gõ --env).
  1. Chọn 3D (lidar, cuboid) hay 2D (ảnh) -> hiện menu ngay.
  2. Chọn mục trong menu -> chọn Gán HẾT hay Chọn gán những gì -> lúc đó mới hỏi số job
     (Enter = job lần trước). Job khác loại -> hỏi có chuyển sang menu kia không.
     Menu 3D: 1 Draw new cuboid (gán hết / chọn nhãn, số vật, Track/Shape, frame / dựa vào job trước)
              | 2 công cụ khác (kiểm tra nhãn, calib camera) | 3 gán theo loại xe (chỉ job ảnh 2D)
     Menu 2D: 1 rectangle | 2 polygon | 3 polyline | 4 mask | 5 skeleton (mỗi kiểu: gán hết / chọn nhãn, frame)
              | 6 nhiều kiểu vẽ cùng lúc | 7 công cụ khác | 8 gán theo loại xe (smart_label.py)
     Mỗi dòng ghi nhãn nào sẽ được gán (khi đã có job); kiểu nào job không dùng được thì ghi lý do.
  3. Chọn "xem trước" hay "đẩy lên CVAT". Số job hỏi 1 lần, bấm J để đổi.
Thao tác đẩy / xoá luôn hỏi lại trước khi chạy.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile

import requests
from dotenv import dotenv_values

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
import sys
if getattr(sys, 'frozen', False):
    HERE = os.path.dirname(sys.executable)
else:
    HERE = SCRIPT_DIR
ENV_FILE = os.path.join(HERE, ".env")
LAST_FILE = os.path.join(HERE, ".menu_last.json")
PY = sys.executable
# Thu muc tach rieng (cvat_2d / cvat_3d) chi co script 1 loai -> menu chi hien loai do
_HAS_3D = os.path.exists(os.path.join(SCRIPT_DIR, "auto_annotate_3d.py"))
_HAS_2D = os.path.exists(os.path.join(SCRIPT_DIR, "auto_shape.py"))
ONLY_DIM = None if _HAS_3D == _HAS_2D else ("3d" if _HAS_3D else "2d")
OTHER_DIR = {"3d": "cvat_2d", "2d": "cvat_3d"}.get(ONLY_DIM)

SHAPES_2D = ["rectangle", "polygon", "polyline", "mask", "skeleton"]
DIM_VI = {"3d": "3D (lidar, cuboid)", "2d": "2D (ảnh)"}
TYPE_VI = {
    "any": "bất kỳ (any)", "cuboid": "cuboid", "rectangle": "rectangle", "polygon": "polygon",
    "polyline": "polyline", "mask": "mask", "skeleton": "skeleton", "points": "points", "ellipse": "ellipse",
    "tag": "tag",
}
SHAPE_HOW = {
    "rectangle": "khung bao vật",
    "polygon": "viền theo hình vật",
    "polyline": "đường tâm dọc vật dài/mảnh",
    "mask": "tô kín vùng vật",
    "skeleton": "điểm mốc mặt / người / bàn tay",
}


# -----------------------------------------------------------------------------
# Tien ich
# -----------------------------------------------------------------------------

def ask(prompt, choices=None, default=None):
    while True:
        try:
            s = input(prompt).strip()
        except EOFError:
            sys.exit(0)
        if not s and default is not None:
            return default
        if choices is None or s.lower() in choices:
            return s.lower() if choices else s
        print(f"  -> Chọn một trong: {', '.join(choices)}")


def yes(prompt):
    return ask(f"{prompt} (c/k): ", ["c", "k", "y", "n"]) in ("c", "y")


def _last_all():
    try:
        return json.load(open(LAST_FILE, encoding="utf-8"))
    except Exception:
        return {}


def load_last():
    """Job lan truoc, nho rieng theo tung file cau hinh (.env / .env.class la 2 CVAT khac nhau)."""
    d = _last_all()
    name = os.path.basename(ENV_FILE)
    return d.get("jobs", {}).get(name) or (d.get("job") if name == ".env" else None)


def save_last(job):
    d = _last_all()
    d.setdefault("jobs", {})[os.path.basename(ENV_FILE)] = job
    if os.path.basename(ENV_FILE) == ".env":
        d["job"] = job
    try:
        json.dump(d, open(LAST_FILE, "w", encoding="utf-8"))
    except Exception:
        pass


def job_info(cfg, job_id):
    s = requests.Session()
    tok = cfg["CVAT_TOKEN"]
    s.headers["Authorization"] = f"{'Bearer' if '.' in tok else 'Token'} {tok}"
    url = cfg["CVAT_URL"].rstrip("/")
    r = s.get(f"{url}/api/jobs/{job_id}", timeout=30)
    if r.status_code == 404:
        raise ValueError(f"Không có job {job_id} (hoặc tài khoản không có quyền)")
    r.raise_for_status()
    j = r.json()
    r = s.get(f"{url}/api/labels", params={"job_id": job_id, "page_size": 500}, timeout=30)
    r.raise_for_status()
    labels = [dict(id=lb["id"], name=lb["name"], type=lb.get("type") or "any", sublabels=lb.get("sublabels", []))
              for lb in r.json().get("results", [])]
    return dict(id=job_id, task=j["task_id"], dim=(j.get("dimension") or "2d").lower(),
                start=j["start_frame"], stop=j["stop_frame"], stage=j.get("stage"), labels=labels)


def labels_for(job, shape):
    ok = ("skeleton",) if shape == "skeleton" else ("any", shape)
    return [lb for lb in job["labels"] if lb["type"] in ok]


def shape_status(job, shape):
    """-> (dung duoc?, mo ta nhan se gan / ly do khong dung duoc)"""
    if job["dim"] == "3d" and shape != "cuboid":
        return False, "job 3D chỉ vẽ được cuboid"
    if job["dim"] != "3d" and shape == "cuboid":
        return False, "chỉ dùng cho job 3D"
    labs = labels_for(job, shape)
    if not labs:
        return False, "job không có nhãn nào vẽ bằng kiểu này"
    if shape == "cuboid":
        from label_check import label_kind
        auto = [lb["name"] for lb in labs if label_kind(lb["name"])]
        manual = [lb["name"] for lb in labs if not label_kind(lb["name"])]
        return bool(auto), (f"gán: {', '.join(auto) or '-'}" + (f" | gán tay: {', '.join(manual)}" if manual else ""))
    if shape == "skeleton":
        from auto_shape import skeleton_kind
        vi = {"face": "mặt", "person": "người", "hand": "bàn tay"}
        parts = [f"{lb['name']} ({vi.get(skeleton_kind(lb), 'không nhận ra')})" for lb in labs]
        return True, ", ".join(parts)
    return True, ", ".join(lb["name"] for lb in labs)


def show_job(job):
    n = job["stop"] - job["start"] + 1
    print(f"\nJob {job['id']} | task {job['task']} | {job['dim'].upper()} | {n} frame "
          f"({job['start']}-{job['stop']}) | giai đoạn: {job['stage']}")
    print(f"  {'Nhãn':26s} Kiểu vẽ trên CVAT")
    for lb in job["labels"]:
        typ = TYPE_VI.get(lb["type"], lb["type"])
        if lb["sublabels"]:
            typ += f" ({len(lb['sublabels'])} điểm)"
        print(f"  {lb['name'][:26]:26s} {typ}")


# -----------------------------------------------------------------------------
# Chay script
# -----------------------------------------------------------------------------

def run(cfg, job, script, args, use_env=True, pause=True):
    """Chay 1 script voi job dang chon. Script doc job tu .env -> tao file .env tam voi job nay."""
    if not use_env and os.path.basename(ENV_FILE) != ".env":
        print(f"\n  -> {script} chỉ đọc file .env (không nhận --env) -> không chạy được với {os.path.basename(ENV_FILE)}")
        ask("Enter để quay lại menu...", default="")
        return 1
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               CVAT_JOB_ID=str(job["id"]), CVAT_TASK_ID=str(job["task"]))
    tmp = None
    if use_env:
        lines = [f"{k}={v}" for k, v in cfg.items() if k not in ("CVAT_JOB_ID", "CVAT_TASK_ID")]
        lines += [f"CVAT_JOB_ID={job['id']}", f"CVAT_TASK_ID={job['task']}"]
        fd, tmp = tempfile.mkstemp(suffix=".env", prefix="cvat_menu_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        args = args + ["--env", tmp]
    cmd = [PY, os.path.join(SCRIPT_DIR, script)] + args
    shown = " ".join(a for a in args if a != tmp and a != "--env")
    print(f"\n>>> {script} {shown}\n" + "-" * 70, flush=True)
    try:
        code = subprocess.call(cmd, cwd=HERE, env=env)
    except KeyboardInterrupt:
        code = "dừng (Ctrl+C)"
    finally:
        if tmp:
            os.remove(tmp)
    print("-" * 70 + f"\n<<< Xong (mã thoát {code})")
    if pause:
        ask("Enter để quay lại menu...", default="")
    return code


def pick_frames(job, all_flag=True):
    """-> tham so frame. all_flag: script can --all khi lam moi frame."""
    if job["start"] == job["stop"]:
        return ["--all"] if all_flag else []
    s = ask(f"    Frame nào? Enter = tất cả, hoặc gõ 1 số ({job['start']}-{job['stop']}): ", default="")
    if s.isdigit():
        return ["--frame", s]
    return ["--all"] if all_flag else []


def pick_labels(labs):
    if len(labs) <= 1:
        return []
    for i, lb in enumerate(labs, 1):
        print(f"      {i}. {lb['name']}")
    s = ask("    Nhãn nào? Enter = tất cả, hoặc gõ số thứ tự (vd 1,3): ", default="")
    idx = [int(x) for x in s.replace(" ", "").split(",") if x.isdigit() and 1 <= int(x) <= len(labs)]
    return ["--labels", ",".join(labs[i - 1]["name"] for i in idx)] if idx else []


# -----------------------------------------------------------------------------
# Tung kieu ve
# -----------------------------------------------------------------------------

def do_cuboid_seq(cfg, job):
    """Gán cuboid dựa vào job trước đã kiểm tra (chuỗi frame liên tiếp)."""
    jid = str(job["id"])
    print("      1. Xem trước (preview_seq/, không đẩy)")
    print("      2. Gán + ĐẨY lên CVAT (job phải trống)")
    print("      3. Job đã có box auto cũ: sao lưu, xoá rồi đẩy mới")
    print(f"      4. Đẩy file preview_seq/job{jid}.json đã sửa tay")
    print("      0. Quay lại")
    m = ask("      Chọn: ", ["0", "1", "2", "3", "4"])
    args = {"1": ["--dry-run"], "2": [], "3": ["--replace"], "4": ["--from-json"]}.get(m)
    if args is None or (m != "1" and not yes(f"      Đẩy lên CVAT job {jid}?")):
        return
    if m != "4" and not yes("      Dùng ảnh camera (chính xác hơn, chậm hơn)?"):
        args.append("--no-camera")
    run(cfg, job, "auto_annotate_seq.py", [jid] + args)


def do_shape(cfg, get_job, shape):
    print(f"\n  --- Draw new {shape} ({SHAPE_HOW[shape]}) ---")
    print(f"    1. Gán HẾT  (mọi nhãn vẽ bằng {shape}, mọi frame)")
    print("    2. Chọn gán những gì  (nhãn nào, frame nào)")
    print("    0. Quay lại")
    k = ask("    Chọn: ", ["0", "1", "2"])
    if k == "0":
        return
    job = get_job()
    if job is None:
        return
    ok, text = shape_status(job, shape)
    if not ok:
        print(f"  -> Không dùng được: {text}")
        return
    jid = str(job["id"])
    lab_args = pick_labels(labels_for(job, shape)) if k == "2" else []
    frames = pick_frames(job, all_flag=False) if k == "2" else []
    print("    1. Xem trước (lưu ảnh vẽ sẵn vào preview_shape/, không đẩy)")
    print("    2. Gán + ĐẨY lên CVAT")
    print(f"    3. Gán + ĐẨY, thay {shape} AUTO cũ cùng nhãn (sao lưu trước, nhãn vẽ tay giữ nguyên)")
    print("    0. Quay lại")
    m = ask("    Chọn: ", ["0", "1", "2", "3"])
    if m == "0" or (m != "1" and not yes(f"    Đẩy lên CVAT job {jid}?")):
        return
    args = [jid, "--shape", shape] + lab_args + frames
    args += {"1": [], "2": ["--push"], "3": ["--push", "--replace"]}[m]
    run(cfg, job, "auto_shape.py", args)


def do_custom_3d(cfg, job, c):
    """c: "1" gán hết, "2" gán theo yêu cầu."""
    jid = str(job["id"])
    print("\n  --- " + {"1": "Gán HẾT (3D)", "2": "Chọn gán những gì (3D)"}[c] + " ---")
    if c == "1":
        print("      1. Xem trước (preview_3d/)\n      2. Gán + ĐẨY (bỏ qua frame đã có box auto)")
        print("      3. Gán + ĐẨY, thay box auto cũ (box vẽ tay giữ nguyên)\n      0. Quay lại")
        m = ask("      Chọn: ", ["0", "1", "2", "3"])
        args = {"1": [], "2": ["--push"], "3": ["--push", "--replace"]}.get(m)
        if args is None or (m != "1" and not yes(f"      Đẩy lên CVAT job {jid}?")):
            return
        run(cfg, job, "auto_annotate_3d.py", ["--all"] + args)
    elif c == "2":
        from label_check import label_kind
        labs = [lb["name"] for lb in labels_for(job, "cuboid")
                if label_kind(lb["name"]) in ("vehicle", "two-wheels", "pedestrian")]
        if not labs:
            print("    -> Job không có nhãn ô tô / xe máy / người -> chưa tự gán theo yêu cầu được")
            return
        args = [jid]
        if len(labs) > 1:
            for i, n in enumerate(labs, 1):
                print(f"      {i}. {n}")
            s = ask("    Gán nhãn nào? (Enter = 1): ", [str(i) for i in range(1, len(labs) + 1)], default="1")
            args += ["--label", labs[int(s) - 1]]
        else:
            print(f"    Nhãn: {labs[0]}")
            args += ["--label", labs[0]]
        while True:
            n = ask("    Gán mấy vật? (Enter = 1, gõ all = tất cả vật của nhãn này): ", default="1")
            if n.isdigit() and int(n) > 0 or n.lower() == "all":
                break
            print("  -> Gõ 1 số (vd 1, 3) hoặc all")
        args += ["--count", n.lower()]
        print("      1. Track  (mỗi vật 1 ID qua nhiều frame)\n      2. Shape  (mỗi frame 1 box riêng)")
        if ask("    Kiểu gán (Enter = 1): ", ["1", "2"], default="1") == "2":
            args += ["--mode", "shape"]
        if job["stop"] > job["start"]:
            fr = ask(f"    Frame nào? Enter = tất cả ({job['start']}-{job['stop']}), hoặc 1 số / đoạn vd 0-30: ", default="")
            if fr.replace("-", "").isdigit():
                args += ["--frames", fr]
        png = os.path.join(HERE, "preview_track", f"job{jid}_candidates.png")
        if os.path.exists(png):
            pk = ask(f"    Chọn đúng vật theo số trên ảnh {os.path.relpath(png, HERE)}? Enter = tự chọn, hoặc gõ số vd 2,5: ",
                     default="")
            if pk.replace(",", "").replace(" ", "").isdigit():
                args += ["--pick", pk.replace(" ", "")]
        print("      1. Xem trước (ảnh + JSON vào preview_track/, không đẩy)\n      2. Gán + ĐẨY lên CVAT\n      0. Quay lại")
        m = ask("      Chọn: ", ["0", "1", "2"])
        if m == "0" or (m == "2" and not yes(f"      Đẩy lên CVAT job {jid}? (chỉ THÊM, không xoá gì)")):
            return
        if m == "2":
            run(cfg, job, "track_objects.py", args + ["--push"])
            return
        code = run(cfg, job, "track_objects.py", args, pause=False)
        print(f"    Xem ảnh: preview_track\\job{jid}_track.png và job{jid}_candidates.png")
        if code == 0 and yes(f"    Đẩy ĐÚNG kết quả vừa xem trước lên CVAT job {jid}?"):
            run(cfg, job, "track_objects.py", [jid, "--from-json"])


def do_custom_2d(cfg, job, c):
    """c: "1" gán hết, "2" gán theo yêu cầu."""
    jid = str(job["id"])
    print("\n  --- " + {"1": "Gán HẾT (2D)", "2": "Chọn gán những gì (2D)"}[c] + " ---")
    labs = [lb for lb in job["labels"] if lb["type"] in ("any", "skeleton", *SHAPES_2D)]
    if not labs:
        print("    -> Job không có nhãn nào tự gán được (rectangle / polygon / polyline / mask / skeleton)")
        return
    if c == "2":
        for i, lb in enumerate(labs, 1):
            print(f"      {i}. {lb['name']:26s} {TYPE_VI.get(lb['type'], lb['type'])}")
        s = ask("    Gán nhãn nào? Enter = tất cả, hoặc gõ số thứ tự (vd 1,3): ", default="")
        idx = [int(x) for x in s.replace(" ", "").split(",") if x.isdigit() and 1 <= int(x) <= len(labs)]
        labs = [labs[i - 1] for i in idx] or labs
    any_shape = "rectangle"
    if any(lb["type"] == "any" for lb in labs):
        opts = ["rectangle", "polygon", "polyline", "mask"]
        print("      Nhãn kiểu 'bất kỳ (any)' vẽ bằng gì?")
        for i, sh in enumerate(opts, 1):
            print(f"        {i}. {sh}  ({SHAPE_HOW[sh]})")
        any_shape = opts[int(ask("      Chọn (Enter = 1): ", ["1", "2", "3", "4"], default="1")) - 1]
    groups = {}
    for lb in labs:
        groups.setdefault(any_shape if lb["type"] == "any" else lb["type"], []).append(lb["name"])
    for sh, names in groups.items():
        print(f"    {sh:10s} <- {', '.join(names)}")
    frames = pick_frames(job, all_flag=False) if c == "2" else []
    print("    1. Xem trước (lưu ảnh vẽ sẵn vào preview_shape/, không đẩy)")
    print("    2. Gán + ĐẨY lên CVAT")
    print("    3. Gán + ĐẨY, thay nhãn AUTO cũ cùng nhãn (sao lưu trước, nhãn vẽ tay giữ nguyên)")
    print("    0. Quay lại")
    m = ask("    Chọn: ", ["0", "1", "2", "3"])
    if m == "0" or (m != "1" and not yes(f"    Đẩy lên CVAT job {jid}?")):
        return
    push = {"1": [], "2": ["--push"], "3": ["--push", "--replace"]}[m]
    items = list(groups.items())
    for k, (sh, names) in enumerate(items):
        run(cfg, job, "auto_shape.py", [jid, "--shape", sh, "--labels", ",".join(names)] + frames + push,
            pause=k == len(items) - 1)


def do_other(cfg, job):
    jid = str(job["id"])
    print("\n  --- Công cụ khác ---")
    if job["dim"] == "3d":
        print(f"    1. Kiểm tra nhãn job {jid} trước khi nộp")
        print(f"    2. Kiểm tra cả task {job['task']}")
        print(f"    3. Cả task + TỰ SỬA nhãn sai rõ ràng (có sao lưu)")
        print("    4. Calib camera cho task   (làm 1 lần khi sang task mới)")
        print("    0. Quay lại")
        c = ask("    Chọn: ", ["0", "1", "2", "3", "4"])
        if c in ("1", "2", "3"):
            args = {"1": [jid], "2": ["--task", str(job["task"])], "3": ["--task", str(job["task"]), "--fix"]}[c]
            if c != "3" or yes("    Sửa nhãn trên CVAT?"):
                run(cfg, job, "label_check.py", args)
        elif c == "4":
            run(cfg, job, "camera_calib.py", ["--job", jid], use_env=False)
        return
    print("    1. Bộ chuẩn AI20K nhanh: box + vùng đi được + lề đường   (YOLO + SegFormer, tên nhãn cố định)")
    print("    2. Bộ chuẩn AI20K SAM2: box chặt + vùng đi được + vạch kẻ đường")
    print("    3. Mask 19 lớp Cityscapes (road, sky, building... — hợp với nền/vùng lớn)")
    print("    4. Mặt 50 điểm kiểu cũ (nhãn face + longmaytrai, mattrai...)")
    print("    5. Xoá nhãn AUTO trong job (nhãn vẽ tay giữ nguyên)")
    print("    0. Quay lại")
    c = ask("    Chọn: ", ["0", "1", "2", "3", "4", "5"])
    if c == "5":
        if yes(f"    Xoá toàn bộ nhãn AUTO của job {jid}?"):
            run(cfg, job, "auto_annotate.py", ["--clear-auto"])
        return
    if c == "0":
        return
    print("      1. Xem trước (không đẩy)\n      2. Gán + ĐẨY lên CVAT\n      0. Quay lại")
    m = ask("      Chọn: ", ["0", "1", "2"])
    if m == "0" or (m == "2" and not yes(f"      Đẩy lên CVAT job {jid}?")):
        return
    push = ["--push"] if m == "2" else []
    frames = pick_frames(job)
    if c == "1":
        run(cfg, job, "auto_annotate.py", frames + push)
    elif c == "2":
        run(cfg, job, "2d_annotation.py", frames + push)
    elif c == "3":
        extra = ["--replace"] if push and yes("      Xoá mask auto cũ ở frame đó trước khi đẩy?") else []
        run(cfg, job, "semantic_segmentation.py", frames + push + extra)
    else:
        run(cfg, job, "auto_annotate_keypoints.py", frames + push, use_env=False)


def ask_all_or_pick(title, pick_desc, extra=None):
    """Hỏi Gán HẾT hay Chọn gán những gì (trước khi hỏi số job). -> "1" | "2" | khoá trong extra | "0"."""
    print(f"\n  --- {title} ---")
    print("    1. Gán HẾT  (mọi nhãn, mọi vật, mọi frame)")
    print(f"    2. Chọn gán những gì  ({pick_desc})")
    for k, text in (extra or {}).items():
        print(f"    {k}. {text}")
    print("    0. Quay lại")
    return ask("    Chọn: ", ["0", "1", "2", *(extra or {})])


def menu_3d(cfg, job, get_job):
    """job None: chưa chọn job -> hiện menu trước, chọn xong mới hỏi số job (get_job)."""
    print("\n=== MENU 3D (lidar) ===")
    if job:
        ok, text = shape_status(job, "cuboid")
        print("  1. Draw new cuboid  " + (f"-> {text}" if ok else f"(không dùng được: {text})"))
    else:
        print("  1. Draw new cuboid  (vẽ hộp 3D cho vật: gán hết / chọn nhãn, số xe, Track hay Shape, frame)")
    print("  2. Công cụ khác (kiểm tra nhãn, calib camera)")
    if ONLY_DIM:
        print("  J. Đổi job     L. Xem lại nhãn của job     0. Thoát")
        c = ask("Chọn: ", ["1", "2", "j", "l", "0"])
    else:
        print("  3. Gán theo loại xe (Xanh SM, ô tô, xe tải...)  (không dùng được: chỉ chạy trên job ảnh 2D)")
        print("  M. Sang menu 2D     J. Đổi job     L. Xem lại nhãn của job     0. Thoát")
        c = ask("Chọn: ", ["1", "2", "3", "m", "j", "l", "0"])
    if c == "3":
        print("  -> Gán theo loại xe nhận xe trên ảnh -> bấm M sang menu 2D")
    elif c == "1":
        k = ask_all_or_pick("Draw new cuboid", "nhãn nào, mấy xe / vật, Track hay Shape, frame nào",
                            {"3": "Gán dựa vào job trước đã kiểm tra  (chuỗi frame liên tiếp)"})
        if k == "0":
            return c
        job = get_job()
        if job is None:             # job vừa nhập là job 2D, đã chuyển menu
            return "x"
        ok, text = shape_status(job, "cuboid")
        if not ok:
            print(f"  -> Không dùng được: {text}")
        elif k == "3":
            do_cuboid_seq(cfg, job)
        else:
            do_custom_3d(cfg, job, k)
    elif c == "2":
        job = get_job()
        if job is None:
            return "x"
        do_other(cfg, job)
    return c


def menu_2d(cfg, job, get_job):
    """job None: chưa chọn job -> hiện menu trước, chọn xong mới hỏi số job (get_job)."""
    print("\n=== MENU 2D (ảnh) — chọn kiểu vẽ giống nút Draw new ... trên CVAT ===")
    for i, shape in enumerate(SHAPES_2D, 1):
        if job:
            ok, text = shape_status(job, shape)
            print(f"  {i}. Draw new {shape:9s} " + (f"-> {text}" if ok else f"(không dùng được: {text})"))
        else:
            print(f"  {i}. Draw new {shape:9s} ({SHAPE_HOW[shape]})")
    shapes = {str(i): shape for i, shape in enumerate(SHAPES_2D, 1)}
    n_custom, n_other, n_xsm = (str(len(SHAPES_2D) + k) for k in (1, 2, 3))
    print(f"  {n_custom}. Nhiều kiểu vẽ cùng lúc (mỗi nhãn vẽ theo kiểu của nó: gán hết / chọn nhãn, frame)")
    print(f"  {n_other}. Công cụ khác (bộ chuẩn AI20K, mask Cityscapes, mặt 50 điểm, xoá nhãn auto)")
    print(f"  {n_xsm}. Gán theo loại xe (Xanh SM, ô tô, xe tải, xe buýt, xe máy, xe đạp — tự chọn loại)")
    keys = ["j", "l", "0"] if ONLY_DIM else ["m", "j", "l", "0"]
    print("  " + ("" if ONLY_DIM else "M. Sang menu 3D     ") + "J. Đổi job     L. Xem lại nhãn của job     0. Thoát")
    c = ask("Chọn: ", list(shapes) + [n_custom, n_other, n_xsm] + keys)
    if c in ("m", "j", "l", "0"):
        return c
    if c in shapes:
        do_shape(cfg, get_job, shapes[c])
        return c
    k = None
    if c == n_custom:
        k = ask_all_or_pick("Nhiều kiểu vẽ cùng lúc", "nhãn nào, kiểu vẽ, frame nào")
        if k == "0":
            return c
    job = get_job()
    if job is None:                 # job vừa nhập là job 3D, đã chuyển menu
        return "x"
    if c == n_custom:
        do_custom_2d(cfg, job, k)
    elif c == n_other:
        do_other(cfg, job)
    elif c == n_xsm:
        print("\n  --- Gán theo loại xe ---")
        run(cfg, job, "smart_label.py", [])
    return c


# -----------------------------------------------------------------------------

def choose_env(arg):
    """-> duong dan file cau hinh. Co --env thi dung luon; co nhieu file .env* thi hoi."""
    if arg:
        p = arg if os.path.isabs(arg) else os.path.join(HERE, arg)
        if not os.path.exists(p):
            raise SystemExit(f"Không thấy file cấu hình {arg}")
        return p
    files = sorted(f for f in glob.glob(os.path.join(HERE, ".env*"))
                   if os.path.basename(f) != ".env.example" and os.path.isfile(f))
    if not files:
        raise SystemExit("Chưa có .env -> copy .env.example thành .env và điền CVAT_URL, CVAT_TOKEN")
    if len(files) == 1:
        return files[0]
    print("\nDùng file cấu hình nào?")
    for i, f in enumerate(files, 1):
        cfg = dotenv_values(f)
        note = " (bài trên lớp)" if os.path.basename(f) == ".env.class" else ""
        print(f"  {i}. {os.path.basename(f):12s} {cfg.get('CVAT_URL', '?')}  job {cfg.get('CVAT_JOB_ID', '?')}{note}")
    dft = next((str(i) for i, f in enumerate(files, 1) if os.path.basename(f) == ".env"), "1")
    c = ask(f"Chọn (Enter = {dft}): ", [str(i) for i in range(1, len(files) + 1)], default=dft)
    return files[int(c) - 1]


def choose_dim():
    if ONLY_DIM:
        print(f"\n  Thư mục này chỉ gán nhãn {DIM_VI[ONLY_DIM]} (job loại kia: dùng thư mục {OTHER_DIR})")
        return ONLY_DIM
    print("\nGán nhãn loại nào?")
    print("  1. 3D  (point cloud lidar — vẽ cuboid)")
    print("  2. 2D  (ảnh — rectangle, polygon, mask, ...)")
    return {"1": "3d", "2": "2d"}[ask("Chọn: ", ["1", "2"])]


def fit_dim(job, dim):
    """Job khac loai da chon -> hoi chuyen menu. -> dim moi, hoac None (chon job khac)."""
    if job["dim"] == dim:
        return dim
    print(f"  -> Job {job['id']} là job {DIM_VI[job['dim']]}, không phải {DIM_VI[dim]}.")
    if ONLY_DIM:
        print(f"  -> Job này chạy bằng menu trong thư mục {OTHER_DIR}. Nhập job khác.")
        return None
    if yes(f"  Chuyển sang menu {job['dim'].upper()}?"):
        return job["dim"]
    return None


def choose_job(cfg, default, dim):
    """-> (job, dim). Job khac loai: hoi chuyen menu hoac nhap job khac."""
    while True:
        s = ask(f"\nSố job {dim.upper()} cần làm (Enter = {default}): " if default
                else f"\nSố job {dim.upper()} cần làm: ", default=str(default) if default else None)
        if not s.isdigit():
            print("  -> Gõ số job, vd 10842")
            continue
        try:
            print("  Đang đọc job trên CVAT...")
            job = job_info(cfg, int(s))
        except Exception as e:
            print(f"  Lỗi: {e}")
            continue
        save_last(job["id"])
        d = fit_dim(job, dim)
        if d:
            return job, d


def main():
    global ENV_FILE
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass
    os.chdir(HERE)
    ap = argparse.ArgumentParser(description="Menu gán nhãn CVAT")
    ap.add_argument("job", nargs="?", type=int, help="Số job (bỏ trống thì menu hỏi)")
    ap.add_argument("--env", help="File cấu hình, vd .env.class (bỏ trống: có nhiều file thì menu hỏi)")
    args = ap.parse_args()
    print("=" * 70 + "\n  MENU GÁN NHÃN CVAT\n" + "=" * 70)
    ENV_FILE = choose_env(args.env)
    cfg = {k: v for k, v in dotenv_values(ENV_FILE).items() if v is not None}
    print(f"  Cấu hình: {os.path.basename(ENV_FILE)}  ({cfg.get('CVAT_URL', '?')})")
    dim = choose_dim()
    job = None
    if args.job:
        try:
            job = job_info(cfg, args.job)
            save_last(job["id"])
        except Exception as e:
            print(f"  Lỗi: {e}")
        if job:
            d = fit_dim(job, dim)
            if d is None:          # giu loai da chon -> nhap job khac
                job = None
            else:
                dim = d
                show_job(job)
    st = dict(job=job, dim=dim)

    def get_job():
        """Số job hỏi SAU khi đã chọn việc cần làm. -> job, hoặc None nếu job khác loại và đã chuyển menu."""
        if st["job"] is None:
            menu_dim = st["dim"]
            st["job"], st["dim"] = choose_job(cfg, load_last() or cfg.get("CVAT_JOB_ID"), menu_dim)
            show_job(st["job"])
            if st["dim"] != menu_dim:
                print(f"  -> Đã chuyển sang menu {st['dim'].upper()}, chọn lại việc cần làm")
                return None
        return st["job"]

    while True:
        c = (menu_3d if st["dim"] == "3d" else menu_2d)(cfg, st["job"], get_job)
        if c == "0":
            return
        if c == "m":
            st["dim"] = "2d" if st["dim"] == "3d" else "3d"
            if st["job"] and st["job"]["dim"] != st["dim"]:
                st["job"] = None    # hỏi job mới khi chọn việc trong menu kia
        elif c == "j":
            st["job"], st["dim"] = choose_job(cfg, st["job"]["id"] if st["job"] else load_last(), st["dim"])
            show_job(st["job"])
        elif c == "l":
            if st["job"]:
                show_job(st["job"])
            else:
                print("  -> Chưa chọn job (chọn việc cần làm thì menu sẽ hỏi số job, hoặc bấm J)")


if __name__ == "__main__":
    import sys
    # Hỗ trợ PyInstaller: Khi chạy file exe mà gọi các script con, 
    # sys.executable sẽ là chính file exe đó. Ta chặn sys.argv để chạy script qua runpy.
    if len(sys.argv) > 1 and sys.argv[1].endswith(".py"):
        import runpy
        script_name = sys.argv[1]
        sys.argv = [script_name] + sys.argv[2:]
        try:
            runpy.run_path(os.path.join(SCRIPT_DIR, script_name), run_name="__main__")
        except KeyboardInterrupt:
            pass
        sys.exit(0)

    try:
        main()
    except KeyboardInterrupt:
        print()
