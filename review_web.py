"""
review_web.py — Trang web review nhan 2D (giong Colab): dien CVAT_URL / TOKEN / TASK / JOB, bam Danh gia,
tool ghi chu loi (sai kich thuoc, sai nhan, thieu, thua, trung) len CVAT bang Issue. KHONG sua nhan.

  review_web.bat            -> mo http://localhost:7860 (chi may nay vao duoc)
  review_web.bat --lan      -> may khac cung mang vao http://<ip may nay>:7860
"""
import argparse
import os
import sys
import threading
import time

import gradio as gr
from dotenv import dotenv_values

import review_core as R

LAN = False
_runners = {}
_gpu_lock = threading.Lock()


def env_defaults(name):
    p = os.path.join(R.HERE, name)
    return dotenv_values(p) if os.path.exists(p) else {}


def env_for(url=None):
    """Cau hinh trong .env (uu tien) hoac .env.class; co url thi lay file co CVAT_URL trung url do."""
    files = [env_defaults(n) for n in (".env", ".env.class")]
    if url:
        for d in files:
            if d.get("CVAT_URL", "").strip().rstrip("/") == url.strip().rstrip("/"):
                return d
    return next((d for d in files if d), {})


def get_runner(mode, cb):
    if mode not in _runners:
        _runners[mode] = R.ToolRunner(mode, cb)
    return _runners[mode]


def table(rv):
    rows = []
    for n, base, _, _, finds in rv.frames:
        for k, f in enumerate(finds, 1):
            rows.append([n if n is not None else "-", base, k, R.KIND_VI[f["kind"]], "LỖI" if f["sure"] else "không chắc",
                         f["label"], f["msg"]])
    return rows


def gallery(rv):
    out = []
    for n, base, nb, pv, finds in rv.frames:
        if finds:
            out.append((pv, f"frame {n if n is not None else '-'} · {base} · {sum(f['sure'] for f in finds)} lỗi, "
                            f"{sum(not f['sure'] for f in finds)} không chắc"))
    return out


def summary(rv, pushed=None):
    st = rv.stats
    if not st:
        return ""
    kinds = {}
    for f in rv.findings:
        kk = kinds.setdefault(R.KIND_VI[f["kind"]], [0, 0])
        kk[0 if f["sure"] else 1] += 1
    acc = st["ok"] / max(1, st["boxes"])
    s = (f"### Kết quả\n"
         f"- **{st['frames']} ảnh, {st['boxes']} box** của người gán · box không có lỗi chắc chắn: **{st['ok']} ({acc:.1%})**\n"
         f"- Ghi chú: **{st['sure']} lỗi** (tool chắc chắn) · **{st['unsure']} không chắc** (nên kiểm tra) · "
         f"thời gian {st['giay'] / 60:.1f} phút\n")
    if kinds:
        s += "- " + " · ".join(f"{k}: {a} lỗi / {b} không chắc" for k, (a, b) in sorted(kinds.items())) + "\n"
    if rv.skipped_labels:
        s += f"- Nhãn tool **không đánh giá được** (bỏ qua): {', '.join(rv.skipped_labels)}\n"
    s += f"- Kết quả lưu ở `{rv.out_dir}` (ket_qua_review.csv, ảnh preview, bản sao annotation)\n"
    if pushed:
        s += (f"\n### Đã đẩy lên CVAT\n- Tạo **{pushed['created']} Issue** trên job {rv.job_id}"
              + (f" (xoá {pushed['removed']} Issue tự động cũ)" if pushed["removed"] else "") + "\n"
              + ("- Kiểm tra nhãn gốc: **KHÔNG thay đổi ✔**\n" if pushed["unchanged"]
                 else "- Kiểm tra nhãn gốc: **CÓ THAY ĐỔI ✘** — có thể có người đang sửa job cùng lúc. Xem annotations_truoc/sau_review.json\n"))
    s += ("\n> Lưu ý: đây là review **tự động** (tool so với nhãn người gán). Tool bắt được khoảng 3/4 số lỗi; "
          "ghi chú *không chắc* có thể là báo nhầm. Vật quá nhỏ (< 30px) tool hay bỏ lọt.")
    return s


def do_review(url, token, task, job, file, mode, rider, auto_push, unsure, replace_old, limit, rv_state):
    logs = []
    cb = logs.append
    rv = R.Review()
    result = {}

    def work():
        try:
            if not token and not LAN:
                tk = env_for(url).get("CVAT_TOKEN")
            else:
                tk = token
            with _gpu_lock:
                runner = get_runner("chinh_xac" if mode.startswith("Chính") else "nhanh", cb)
                rv.run(url=url.strip() if url else None, token=(tk or "").strip() or None,
                       task_id=int(task) if str(task).strip() else None, job_id=int(job) if str(job).strip() else None,
                       zip_path=file, rider_person=rider, cb=cb, runner=runner,
                       max_frames=int(limit) if limit else None)
            if auto_push and rv.job_id:
                result["pushed"] = rv.push(include_unsure=unsure, replace_old=replace_old, cb=cb)
        except Exception as e:          # bao loi ro rang cho nguoi dung
            cb(f"❌ LỖI: {e}")
            result["error"] = str(e)

    th = threading.Thread(target=work, daemon=True)
    th.start()
    while th.is_alive():
        time.sleep(0.7)
        yield "\n".join(logs[-60:]), gr.update(), gr.update(), gr.update(), rv_state
    final_sum = summary(rv, result.get("pushed")) if not result.get("error") else f"### ❌ {result['error']}"
    yield "\n".join(logs[-60:]), final_sum, table(rv), gallery(rv), rv


def do_push(unsure, replace_old, rv):
    if rv is None or not getattr(rv, "stats", None):
        return "### Chưa có kết quả review nào để đẩy. Bấm **Đánh giá** trước.", gr.update()
    logs = []
    try:
        res = rv.push(include_unsure=unsure, replace_old=replace_old, cb=logs.append)
        return summary(rv, res), "\n".join(logs)
    except Exception as e:
        return f"### ❌ {e}", "\n".join(logs)


def build():
    d = env_for()
    with gr.Blocks(title="Review nhãn CVAT") as app:
        gr.Markdown("# 🔍 Review nhãn CVAT (2D)\n"
                    "Tool xem lại nhãn người gán: **box đúng không ghi gì**; box sai kích thước / sai nhãn / thiếu / thừa / trùng "
                    "được ghi chú bằng **Issue** trên CVAT. **Không sửa, không thêm, không xoá nhãn nào.**  \n"
                    f"Máy đang chạy: **{R.ToolRunner.device()}**")
        rv_state = gr.State(None)
        with gr.Row():
            with gr.Column(scale=3):
                url = gr.Textbox(label="CVAT_URL", value=d.get("CVAT_URL", "http://localhost:8080"))
                token = gr.Textbox(label="CVAT_TOKEN", type="password",
                                   placeholder="dán token" + ("" if LAN else " (để trống = dùng token trong .env.class / .env)"))
                with gr.Row():
                    task = gr.Textbox(label="CVAT_TASK_ID (không bắt buộc, để kiểm tra đúng task)",
                                      value=d.get("CVAT_TASK_ID", ""))
                    job = gr.Textbox(label="CVAT_JOB_ID", value=d.get("CVAT_JOB_ID", ""))
                file = gr.File(label="File export (không bắt buộc): .zip CVAT for images 1.1 / COCO / YOLO. "
                                     "Không có số job → chỉ đánh giá file, không đẩy lên CVAT.",
                               file_types=[".zip"], type="filepath")
            with gr.Column(scale=2):
                mode = gr.Radio(["Chính xác (4 model + SAM2)", "Nhanh (2 model, cho máy yếu — kém chính xác hơn)"],
                                value="Chính xác (4 model + SAM2)", label="Chế độ")
                rider = gr.Checkbox(value=True, label="Người lái xe máy có box 'person' riêng (bỏ chọn nếu job không gán người lái)")
                auto_push = gr.Checkbox(value=True, label="Đánh giá xong tự đẩy Issue lên CVAT")
                unsure = gr.Checkbox(value=True, label="Đẩy cả ghi chú 'không chắc' (ghi rõ là không chắc)")
                replace_old = gr.Checkbox(value=True, label="Xoá Issue review tự động của lần trước (chỉ Issue do tool tạo)")
                limit = gr.Number(value=None, label="Chỉ chạy N frame đầu (để thử nhanh, trống = tất cả)", precision=0)
        with gr.Row():
            btn = gr.Button("▶ Đánh giá", variant="primary")
            btn_push = gr.Button("⬆ Đẩy Issue lên CVAT")
        log = gr.Textbox(label="Tiến độ", lines=10, max_lines=10, autoscroll=True)
        res = gr.Markdown()
        gal = gr.Gallery(label="Ảnh có ghi chú (đỏ = lỗi, vàng = không chắc, nét đứt = vật bị thiếu; số = thứ tự trong bảng)",
                         columns=2, height="auto", object_fit="contain")
        tbl = gr.Dataframe(headers=["frame", "ảnh", "số", "loại", "mức", "nhãn", "ghi chú"], wrap=True,
                           label="Danh sách ghi chú")
        btn.click(do_review, [url, token, task, job, file, mode, rider, auto_push, unsure, replace_old, limit, rv_state],
                  [log, res, tbl, gal, rv_state])
        btn_push.click(do_push, [unsure, replace_old, rv_state], [res, log])

        def reload_env():               # sua .env roi tai lai trang (F5) la nhan job moi, khong can mo lai web
            e = env_for()
            return e.get("CVAT_URL", "http://localhost:8080"), e.get("CVAT_TASK_ID", ""), e.get("CVAT_JOB_ID", "")
        app.load(reload_env, None, [url, task, job])
    return app


def main():
    global LAN
    ap = argparse.ArgumentParser()
    ap.add_argument("--lan", action="store_true", help="cho may khac cung mang vao (khong dung token mac dinh trong .env)")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    LAN = args.lan
    app = build()
    os.makedirs(R.OUT_ROOT, exist_ok=True)
    if LAN:
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            print(f"May khac cung mang vao: http://{s.getsockname()[0]}:{args.port}", flush=True)
        except OSError:
            pass
    app.queue(default_concurrency_limit=1).launch(server_name="0.0.0.0" if LAN else "127.0.0.1", server_port=args.port,
                                                  inbrowser=not args.no_browser, allowed_paths=[R.OUT_ROOT],
                                                  footer_links=[])


if __name__ == "__main__":
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass
    main()
