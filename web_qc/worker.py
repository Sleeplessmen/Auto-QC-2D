"""
worker.py — Hang doi review: 1 GPU chay lan luot tung job. Moi lan review dung 1 KET NOI CVAT (URL + token + to chuc)
chon tren web; khong chon thi dung ket noi mac dinh. Giu ket qua trong bo nho de day Issue; tat web roi mo lai
van day duoc (dung lai tu file trong review_out/).
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


def env_config():
    """Gia tri trong cvat_2d/.env (doc lai moi lan) — dung de nhap san lam 1 ket noi va dien san so job/task."""
    e = dotenv_values(ENV_PATH) if os.path.exists(ENV_PATH) else {}
    num = lambda v: int(v) if str(v or "").strip().isdigit() else None
    return dict(url=(e.get("CVAT_URL") or "").strip(), token=(e.get("CVAT_TOKEN") or "").strip(),
                org=(e.get("CVAT_ORG") or "").strip(), task_id=num(e.get("CVAT_TASK_ID")), job_id=num(e.get("CVAT_JOB_ID")))


def connection_for(cid):
    """Ket noi (url, token, org) theo id; khong co -> ket noi mac dinh."""
    c = store.get_connection(cid) if cid else None
    c = c or store.default_connection()
    if not c or not c.get("url") or not c.get("token"):
        raise RuntimeError("Chưa có kết nối CVAT nào. Vào trang Kết nối CVAT để thêm.")
    return c


def cvat_client(cid):
    c = connection_for(cid)
    return R.Cvat(c["url"], c["token"], c.get("org") or None), c


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

    def _frames_left(self, run_id):
        """So anh con phai cham cua 1 lan review (dang chay: theo log [i/n]; dang cho: theo goi y luc tao)."""
        import re
        for line in reversed(self.logs.get(run_id, [])):
            m = re.search(r"\[(\d+)/(\d+)\]", line)
            if m:
                return int(m.group(2)) - int(m.group(1))
        r = store.get_run(run_id) or {}
        p = r.get("params") or {}
        return p.get("max_frames") or p.get("frames_hint") or 50

    def eta(self, run_id):
        """Uoc luong so giay den khi lan review nay xong (gom ca cac lan dung truoc trong hang doi)."""
        spi = store.avg_sec_per_image()
        ahead = ([self.current] if self.current and self.current != run_id else []) + \
                self.waiting[:self.waiting.index(run_id)] if run_id in self.waiting else []
        total = sum(self._frames_left(r) for r in ahead) + self._frames_left(run_id)
        return round(total * spi + (20 if not self.runners else 0))

    def log_tail(self, run_id, n=120):
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
                self.logs.setdefault(run_id, []).append(f"❌ LỖI: {e}")
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
        cb = self.logs.setdefault(run_id, []).append
        store.update_run(run_id, status="dang_chay", started=time.time())
        conn = connection_for(run.get("connection_id")) if run["job_id"] else None
        if conn:
            cb(f"Kết nối: {conn['name']} ({conn['url']}{' · tổ chức ' + conn['org'] if conn.get('org') else ''})")
        g = store.get_guideline(run["guideline_id"])
        rules, warn = G.parse_rules(g["rules"]) if g and g.get("rules") else ({}, [])
        if g:
            n_rules = len(rules.get("nhan") or {})
            cb(f"Guideline: {g['name']}" + (f" · file luật {n_rules} nhãn" if rules else " · chưa có file luật (chỉ dùng để tra cứu)"))
        else:
            cb("Không dùng guideline: chỉ chạy tầng 2 (so với model).")
        for w in warn:
            cb(f"  Cảnh báo file luật: {w}")
        mode = p.get("mode", "chinh_xac")
        if mode not in self.runners:
            self.runners[mode] = R.ToolRunner(mode, cb)
        rv = R.Review()
        with G.apply_to_core(rules, R):
            rv.run(url=conn["url"] if conn else None, token=conn["token"] if conn else None, org=(conn or {}).get("org") or None,
                   task_id=run["task_id"], job_id=run["job_id"], zip_path=p.get("file"),
                   mode=mode, rider_person=G.rider_rule(rules, p.get("rider", True)), cb=cb,
                   runner=self.runners[mode], max_frames=p.get("max_frames"))
        store.update_run(run_id, out_dir=rv.out_dir)

        # thong tin job de thong ke theo labeler
        if rv.cvat:
            try:
                job = rv.cvat.job(rv.job_id)
                a = job.get("assignee") or {}
                meta = dict(task_id=job.get("task_id"), job_stage=job.get("stage"), job_state=job.get("state"),
                            assignee=(a.get("username") or "") + (f" ({a['first_name']})" if a.get("first_name") else ""))
                try:
                    t = rv.cvat.get(f"/api/tasks/{job['task_id']}").json()
                    meta.update(task_name=t.get("name"), project_name=(t.get("project") or {}).get("name") if isinstance(t.get("project"), dict) else None)
                except Exception:
                    pass
                store.update_run(run_id, **{k: v for k, v in meta.items() if v is not None})
            except Exception as e:
                cb(f"  (Không lấy được thông tin job: {e})")

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
        kinds = {}
        for f in rv.findings:
            kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
        st["kinds"] = kinds
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
        pdir = os.path.join(run["out_dir"], "preview")
        pv = sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []
        names = {}
        for f in rv.findings:
            names.setdefault((f["frame"], f["name"]), []).append(f)
        rv.frames = []
        for fn in pv:                         # ten preview: 0001_<ten anh>.jpg
            stem = fn.split("_", 1)[1].rsplit(".", 1)[0] if "_" in fn else fn
            key = next((k for k in names if os.path.splitext(k[1])[0][:40] == stem), (None, stem))
            rv.frames.append((key[0], key[1], None, os.path.join(pdir, fn), names.get(key, [])))
        self.reviews[run_id] = rv
        return rv

    def push(self, run_id, ids, replace_old=True, note_ids=(), summary=False, report_url=None):
        rv = self.review_obj(run_id)
        if rv is None:
            raise RuntimeError("Không tìm thấy kết quả review này.")
        if not rv.job_id:
            raise RuntimeError("Lần review này chỉ đánh giá file, không gắn với job CVAT nên không đẩy được.")
        run = store.get_run(run_id)
        cb = self.logs.setdefault(run_id, []).append
        with self.push_lock:
            if rv.cvat is None:
                rv.cvat, _ = cvat_client(run.get("connection_id"))
                rv.before = json.load(open(os.path.join(rv.out_dir, "annotations_truoc_review.json"), encoding="utf-8"))
            keep = rv.findings
            skip = {fid for fid, fb in store.get_feedback(run_id).items() if fb["verdict"] == "tool_nham"}
            edits = store.get_edits(run_id)
            pick = []
            for i in sorted(set(ids)):
                if 0 <= i < len(keep) and i not in skip:
                    f = dict(keep[i])
                    if i in edits:                      # nguoi review da sua loi nhan
                        f["msg"] = edits[i]
                    pick.append(f)
            want_notes = set(note_ids or ())
            for n in store.get_notes(run_id):           # ghi chu tay cua nguoi review (khung ve tren anh)
                if n["id"] in want_notes:
                    pick.append(dict(kind="ghi_chu", sure=True, label="", box=n["box"], ref=f"note {n['id']}",
                                     msg=n["msg"], frame=n["frame"], name=n["name"]))
            if summary and (pick or rv.frames):
                st = rv.stats or {}
                pct = st["ok"] / st["boxes"] if st.get("boxes") else 0
                thr = store.get_settings()["pass_threshold"]
                frame0 = min((f["frame"] for f in pick if f["frame"] is not None), default=rv.frames[0][0] if rv.frames else 0)
                text = (f"Kết quả QC lần #{run_id}: {pct:.0%} box đúng — {'ĐẠT' if pct >= thr else f'CHƯA ĐẠT (cần ≥ {thr:.0%})'}. "
                        f"Có {len(pick)} chỗ cần xem, mỗi chỗ là 1 Issue trên ảnh.")
                if report_url:
                    text += f"\nXem tất cả lỗi kèm ảnh: {report_url}"
                pick.append(dict(kind="tong_ket", sure=True, label="", box=[4, 4, 64, 64], ref=f"run {run_id}", msg=text, frame=frame0, name=""))
            try:
                rv.findings = pick
                res = rv.push(include_unsure=True, replace_old=replace_old, cb=cb)
            finally:
                rv.findings = keep
        res["ids"] = sorted(set(ids) - skip)
        res["time"] = time.time()
        store.update_run(run_id, pushed=res)
        return res

    def job_issues(self, run_id):
        """Issue do tool tao tren job cua lan review nay (de theo doi da sua hay chua)."""
        run = store.get_run(run_id)
        if not run or not run["job_id"]:
            return []
        cv, _ = cvat_client(run.get("connection_id"))
        out = []
        for it in cv.issues(run["job_id"]):
            first = cv.first_comment(it["id"])
            if not first.startswith(R.PREFIX):
                continue
            out.append(dict(id=it["id"], frame=it.get("frame"), resolved=bool(it.get("resolved")),
                            message=first[len(R.PREFIX):].split(" [qc:")[0].strip(), comments=cv.comment_count(it["id"]),
                            updated=it.get("updated_date")))
        return out
