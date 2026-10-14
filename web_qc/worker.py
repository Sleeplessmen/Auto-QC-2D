"""
worker.py — Hang doi review: 1 GPU chay lan luot tung job. Giu ket qua trong bo nho de day Issue,
tat web roi mo lai van day duoc (dung lai tu file trong review_out/).
"""
import json
import os
import queue
import threading
import time
import traceback

from dotenv import dotenv_values

import review_core as R
import guideline as G
import store

ENV_PATH = os.path.join(R.HERE, ".env")


def cvat_config():
    """Doc lai .env moi lan goi: doi CVAT_URL / TOKEN / TASK / JOB trong .env la web dung ngay."""
    e = dotenv_values(ENV_PATH) if os.path.exists(ENV_PATH) else {}
    num = lambda v: int(v) if str(v or "").strip().isdigit() else None
    return dict(url=(e.get("CVAT_URL") or "").strip(), token=(e.get("CVAT_TOKEN") or "").strip(),
                task_id=num(e.get("CVAT_TASK_ID")), job_id=num(e.get("CVAT_JOB_ID")))


class Worker:
    def __init__(self):
        self.q = queue.Queue()
        self.waiting = []           # run id dang cho, theo thu tu
        self.current = None
        self.logs = {}              # run id -> [dong log]
        self.reviews = {}           # run id -> review_core.Review (de day Issue)
        self.runners = {}
        self.push_lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    # ------------------------------------------------------------ hang doi
    def submit(self, run_id):
        self.waiting.append(run_id)
        self.logs[run_id] = ["Đã vào hàng đợi."]
        self.q.put(run_id)

    def position(self, run_id):
        return self.waiting.index(run_id) + 1 if run_id in self.waiting else 0

    def log_tail(self, run_id, n=80):
        lines = self.logs.get(run_id)
        if lines is None:
            r = store.get_run(run_id)
            p = os.path.join(r["out_dir"], "log.txt") if r and r.get("out_dir") else None
            lines = open(p, encoding="utf-8").read().splitlines() if p and os.path.exists(p) else []
        return lines[-n:]

    def _loop(self):
        while True:
            run_id = self.q.get()
            if run_id in self.waiting:
                self.waiting.remove(run_id)
            self.current = run_id
            try:
                self._run(run_id)
            except Exception as e:
                self.logs[run_id].append(f"❌ LỖI: {e}")
                print(traceback.format_exc(), flush=True)
                store.update_run(run_id, status="loi", error=str(e), finished=time.time())
            finally:
                self.current = None
                r = store.get_run(run_id)
                if r and r.get("out_dir") and os.path.isdir(r["out_dir"]):
                    with open(os.path.join(r["out_dir"], "log.txt"), "w", encoding="utf-8") as f:
                        f.write("\n".join(self.logs.get(run_id, [])))

    # ------------------------------------------------------------ 1 lan review
    def _run(self, run_id):
        run = store.get_run(run_id)
        p = run["params"] or {}
        cb = self.logs[run_id].append
        store.update_run(run_id, status="dang_chay", started=time.time())
        cfg = cvat_config()
        g = store.get_guideline(run["guideline_id"])
        rules, warn = G.parse_rules(g["rules"]) if g and g.get("rules") else ({}, [])
        if g:
            cb(f"Guideline: {g['name']}" + ("" if rules else " (chưa có file luật — chỉ dùng để tra cứu)"))
        for w in warn:
            cb(f"  Cảnh báo file luật: {w}")
        mode = p.get("mode", "chinh_xac")
        if mode not in self.runners:
            self.runners[mode] = R.ToolRunner(mode, cb)
        rv = R.Review()
        with G.apply_to_core(rules, R):
            rv.run(url=cfg["url"] if run["job_id"] else None, token=cfg["token"] if run["job_id"] else None,
                   task_id=run["task_id"], job_id=run["job_id"], zip_path=p.get("file"),
                   mode=mode, rider_person=G.rider_rule(rules, p.get("rider", True)), cb=cb,
                   runner=self.runners[mode], max_frames=p.get("max_frames"))
        store.update_run(run_id, out_dir=rv.out_dir)

        # tang 1: kiem tra theo luat guideline (can annotation goc tu CVAT)
        if rules and rv.cvat:
            job = rv.cvat.job(rv.job_id)
            labels = rv.cvat.labels(rv.job_id, job["task_id"])
            frames, _ = rv.cvat.frames(rv.job_id, job)
            done = {f[0] for f in rv.frames}
            frames = [f for f in frames if f[0] in done]
            f1, w1 = G.rule_check(rv.before, labels, frames, rules)
            for w in w1:
                cb(f"  {w}")
            by_frame = {f[0]: f[4] for f in rv.frames}
            for f in f1:
                by_frame.get(f["frame"], []).append(f)
            rv.findings += f1
            cb(f"Tầng 1 (luật guideline): {sum(f['sure'] for f in f1)} lỗi, {sum(not f['sure'] for f in f1)} không chắc.")
        elif rules:
            cb("Tầng 1 (luật guideline) chỉ chạy khi review theo số job (cần nhãn gốc trên CVAT).")
        st = rv.stats
        bad = {(f["frame"], f["ref"]) for f in rv.findings if f["sure"] and f.get("ref")}
        st.update(sure=sum(f["sure"] for f in rv.findings), unsure=sum(not f["sure"] for f in rv.findings),
                  ok=max(0, st["boxes"] - len(bad)))
        rv.stats = st
        rv.save_report()
        self.reviews[run_id] = rv
        store.update_run(run_id, status="xong", stats=st, finished=time.time())
        cb(f"Xong: {st['frames']} ảnh, {st['boxes']} box, {st['ok'] / max(1, st['boxes']):.1%} box không có lỗi chắc chắn.")

        if p.get("auto_push") and rv.job_id:
            ids = [i for i, f in enumerate(rv.findings) if f["sure"] or p.get("push_unsure")]
            self.push(run_id, ids, replace_old=True)

    # ------------------------------------------------------------ ket qua + day Issue
    def review_obj(self, run_id):
        rv = self.reviews.get(run_id)
        if rv is not None:
            return rv
        run = store.get_run(run_id)
        if not run or run["status"] != "xong" or not run.get("out_dir"):
            return None
        res = json.load(open(os.path.join(run["out_dir"], "ket_qua_review.json"), encoding="utf-8"))
        rv = R.Review()
        rv.out_dir, rv.job_id, rv.stats = run["out_dir"], run["job_id"], res["stats"]
        rv.findings = res["findings"]
        rv.skipped_labels = res.get("skipped_labels", [])
        pv = sorted(os.listdir(os.path.join(run["out_dir"], "preview"))) if os.path.isdir(os.path.join(run["out_dir"], "preview")) else []
        names = {}
        for f in rv.findings:
            names.setdefault((f["frame"], f["name"]), []).append(f)
        rv.frames = []
        for fn in pv:                         # ten preview: 0001_<ten anh>.jpg
            stem = fn.split("_", 1)[1].rsplit(".", 1)[0] if "_" in fn else fn
            key = next((k for k in names if os.path.splitext(k[1])[0][:40] == stem), (None, stem))
            rv.frames.append((key[0], key[1], None, os.path.join(run["out_dir"], "preview", fn), names.get(key, [])))
        self.reviews[run_id] = rv
        return rv

    def push(self, run_id, ids, replace_old=True):
        rv = self.review_obj(run_id)
        if rv is None:
            raise RuntimeError("Không tìm thấy kết quả review này.")
        if not rv.job_id:
            raise RuntimeError("Lần review này chỉ đánh giá file, không gắn với job CVAT nên không đẩy được.")
        cfg = cvat_config()
        cb = self.logs.setdefault(run_id, []).append
        with self.push_lock:
            if rv.cvat is None:
                rv.cvat = R.Cvat(cfg["url"], cfg["token"])
                rv.before = json.load(open(os.path.join(rv.out_dir, "annotations_truoc_review.json"), encoding="utf-8"))
            keep = rv.findings
            pick = [keep[i] for i in sorted(set(ids)) if 0 <= i < len(keep)]
            try:
                rv.findings = pick
                res = rv.push(include_unsure=True, replace_old=replace_old, cb=cb)
            finally:
                rv.findings = keep
        res["ids"] = sorted(set(ids))
        res["time"] = time.time()
        store.update_run(run_id, pushed=res)
        return res
