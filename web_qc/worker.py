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


def guess_tool_classes(labels):
    """{ten nhan: lop tool | 'road'} — de doc guideline biet cau nao noi ve nhan nao."""
    import area_check
    names = [lb["name"] for lb in labels]
    tool2job, _, _ = R.build_label_map(names)
    out = {j: c for c, j in tool2job.items() if j and c != "GreenSM"}
    for n in area_check.road_labels(names):
        out[n] = "road"
    return out


class Worker:
    def __init__(self):
        self.q = queue.Queue()
        self.waiting = []           # run id dang cho, theo thu tu
        self.current = None
        self.logs = {}              # run id -> [dong log]
        self.reviews = {}           # run id -> review_core.Review (de day Issue)
        self.runners = {}
        self.push_lock = threading.Lock()
        self.poll_error = None
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._poll_loop, daemon=True).start()

    # ------------------------------------------------------------ tu review khi job sang 'validation'
    POLL_SEC = 60

    def _poll_loop(self):
        while True:
            time.sleep(self.POLL_SEC)
            try:
                self.poll_validation()
                self.poll_error = None
            except Exception as e:
                self.poll_error = str(e)
                print(f"[tu dong] loi khi hoi CVAT: {e}", flush=True)

    def poll_validation(self):
        """Hoi CVAT cac job dang o stage 'validation'. Job moi vao validation (lan hoi truoc chua thay) -> xep 1 lan review.
        Lan dau bat: chi ghi nhan cac job dang co, khong chay (tranh chay don ca loat job cu).
        Job bi tra ve annotation roi nop lai validation -> review lai."""
        s = store.get_settings()
        if not s["auto_validation"]:
            return []
        c = connection_for(s["auto_connection_id"])
        cv, _ = cvat_client(c["id"])
        jobs, page = [], 1
        while True:
            r = cv.get("/api/jobs", stage="validation", page=page, page_size=100).json()
            jobs += r["results"]
            if not r.get("next"):
                break
            page += 1
        key = str(c["id"])
        seen_all = dict(s.get("auto_seen") or {})
        first = key not in seen_all
        before = set(seen_all.get(key) or [])
        now = {j["id"] for j in jobs if j.get("dimension") != "3d"}
        busy = {store.get_run(r)["job_id"] for r in self.waiting + ([self.current] if self.current else [])}
        made = []
        if not first:
            for j in jobs:
                if j["id"] not in now or j["id"] in before or j["id"] in busy:
                    continue
                params = dict(mode=s["default_mode"], rider=True, max_frames=None, auto_push=bool(s["auto_push"]),
                              auto_return=bool(s["auto_push"] and s.get("auto_return")),
                              push_unsure=False, frames_hint=j.get("frame_count"))
                rid = store.new_run(j["id"], j["task_id"], "tự động", params, store.task_guideline(j["task_id"]), c["id"],
                                    source="validation")
                self.submit(rid)
                made.append(rid)
        seen_all[key] = sorted(now)
        store.set_settings(auto_seen=seen_all, auto_last=dict(time=time.time(), jobs=len(now), started=len(made),
                                                              first=first, connection=c["name"]))
        return made

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
        if g and rules:
            cb(f"Guideline: {g['name']} · file luật {len(rules.get('nhan') or {})} nhãn (người QC đã soạn)")
            if conn and g.get("text"):
                # file luat de trong muc nao (vd shape/track, polygon kem box) thi lay theo chu trong guideline
                try:
                    cv, _ = cvat_client(run.get("connection_id"))
                    labels = cv.labels(run["job_id"], cv.job(run["job_id"])["task_id"])
                    auto, ev = G.extract_rules(g["text"], labels, guess_tool_classes(labels))
                    q = rules.setdefault("quy_tac", {})
                    add = {k: v for k, v in (auto.get("quy_tac") or {}).items() if q.get(k) in (None, "")}
                    q.update(add)
                    for e in ev:
                        if e["luat"] in add:
                            cb(f"  + theo guideline: {e['luat']}: {e['gia_tri']}" + (f" (mục {e['muc']})" if e["muc"] else ""))
                except Exception as e:
                    cb(f"  (Không đọc thêm được yêu cầu từ chữ trong guideline: {e})")
        elif g and conn and g.get("text"):
            # chua co file luat: tu doc guideline lay yeu cau, ket hop voi nhan cua task
            try:
                cv, _ = cvat_client(run.get("connection_id"))
                labels = cv.labels(run["job_id"], cv.job(run["job_id"])["task_id"])
                rules, ev = G.extract_rules(g["text"], labels, guess_tool_classes(labels))
                cb(f"Guideline: {g['name']} · chưa có file luật → tool tự đọc guideline, lấy được {len(ev)} yêu cầu:")
                for e in ev[:12]:
                    cb(f"  • {e['luat']}: {e['gia_tri']}" + (f" (mục {e['muc']})" if e["muc"] else "") + f" — \"{e['trich'][:90]}\"")
            except Exception as e:
                cb(f"Guideline: {g['name']} · không tự đọc được yêu cầu ({e}), chỉ dùng để tra cứu.")
        elif g:
            cb(f"Guideline: {g['name']} · chưa có file luật (chỉ dùng để tra cứu)")
        else:
            cb("Không dùng guideline: review dựa vào nhãn của task (so với model).")
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
            # tang luat hinh hoc (rule_tier) da bao cung chuyen (ra ngoai anh / khong co dien tich) -> bo ban trung
            topic = lambda m: "ngoai" if "ngoài ảnh" in m else "dt" if "không có diện tích" in m else None
            had = {(f["frame"], f.get("ref"), topic(f["msg"])) for f in rv.findings if topic(f["msg"])}
            f1 = [f for f in f1 if (f["frame"], f.get("ref"), topic(f["msg"])) not in had]
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
            if p.get("auto_return"):
                self.return_job(rv, cb, run_id)

    def return_job(self, rv, cb, run_id=None):
        """Nhu LetmeQC: con loi chac chan (tru loi nguoi review danh 'tool nham') -> tra job ve annotation, trang thai
        rejected, giu nguoi duoc giao. Khong co loi chac chan -> giu job o validation de reviewer kiem cheo.
        Ket qua luu vao run.returned ('tra_ve' / 'giu' / 'loi') cho trang Tu review."""
        n = sum(1 for f in rv.findings if f["sure"])
        if not n:
            cb("Không có lỗi chắc chắn: job ở lại validation để reviewer kiểm chéo.")
            res = "giu"
        else:
            r = rv.cvat.s.patch(f"{rv.cvat.url}/api/jobs/{rv.job_id}", json=dict(stage="annotation", state="rejected"), timeout=60)
            if r.ok:
                cb(f"Có {n} lỗi chắc chắn: đã trả job {rv.job_id} về annotation (rejected) cho annotator sửa.")
                res = "tra_ve"
            else:
                cb(f"  Không trả được job về annotation ({r.status_code}: {r.text[:200]}). Reviewer trả tay trên CVAT.")
                res = "loi"
        if run_id is not None:
            store.update_run(run_id, returned=res)

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
                text = (f"Tổng kết (không phải lỗi): {pct:.0%} box đúng —{'ĐẠT' if pct >= thr else f'CHƯA ĐẠT (cần ≥ {thr:.0%})'}. "
                        f"{len(pick)} lỗi cần sửa.")
                if report_url:
                    text += f"\nDanh sách lỗi: {report_url}"
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

    def effect(self, job_ids=None, days=30):
        """Hieu qua Issue tren CVAT (hieu_qua.py) cho cac job da day Issue trong `days` ngay. Nho ket qua 5 phut."""
        import hieu_qua
        since = time.time() - max(1, days) * 86400
        runs = [r for r in store.list_runs(limit=5000) if r["job_id"] and r["created"] >= since]
        jobs = {}
        for r in runs:
            jobs.setdefault(r["job_id"], []).append(r)
        if job_ids:
            jobs = {j: v for j, v in jobs.items() if j in set(job_ids)}
        cache = self.__dict__.setdefault("_effect_cache", {})
        items, errors = [], []
        for jid, rs in jobs.items():
            if not any(r.get("pushed") for r in rs):
                continue
            key = (jid, max(r["id"] for r in rs))
            hit = cache.get(key)
            if hit and time.time() - hit[0] < 300:
                items.append(hit[1])
                continue
            try:
                cv, _ = cvat_client(rs[0].get("connection_id"))
                fb = {r["id"]: store.get_feedback(r["id"]) for r in rs}
                e = hieu_qua.job_effect(cv, jid, rs, fb)
                e["assignee"] = next((r.get("assignee") for r in rs if r.get("assignee")), None)
                cache[key] = (time.time(), e)
                items.append(e)
            except Exception as ex:
                errors.append(f"job {jid}: {ex}")
        out = hieu_qua.summary(items)
        out["errors"] = errors
        return out

    def job_issues(self, run_id):
        """Issue do tool tao tren job cua lan review nay (de theo doi da sua hay chua)."""
        run = store.get_run(run_id)
        if not run or not run["job_id"]:
            return []
        cv, _ = cvat_client(run.get("connection_id"))
        out = []
        for it in cv.issues(run["job_id"]):
            ti = R.tool_issue(cv.first_comment(it["id"]))
            if ti is None:
                continue
            out.append(dict(id=it["id"], frame=it.get("frame"), resolved=bool(it.get("resolved")),
                            message=ti[1], comments=cv.comment_count(it["id"]),
                            updated=it.get("updated_date")))
        return out
