"""
hieu_qua.py — Do HIEU QUA cua QC tu dong tren job that (sau khi annotator sua theo Issue).

Moi Issue tool tao co ma [qc:frame|loai|vat] o cuoi. So nhan LUC REVIEW (annotations_truoc_review.json cua lan review
da tao Issue do) voi nhan HIEN TAI tren CVAT:
  - da_sua     : vat bi Issue chi ra da duoc sua / xoa, hoac cho bao thieu da co vat moi  -> Issue DUNG
  - khong_sua  : Issue da dong (resolved) ma nhan khong doi                              -> Issue SAI (tool bao nham)
  - tool_nham  : nguoi review danh dau "tool nham" tren web (khong day len)              -> Issue SAI
  - chua_xu_ly : Issue con mo, nhan chua doi                                             -> chua tinh
  - khong_ro   : khong co lan review nao (tren web nay) TRUOC luc Issue duoc tao -> khong biet nhan luc do
                 (vd Issue do ban web khac tao) -> khong tinh, tranh ket luan sai
Issue do NGUOI tao (khong co ma qc) = loi reviewer tim them khi review cheo, tool bo sot.

Chi so:
  ti_le_issue_dung        = da_sua / (da_sua + khong_sua + tool_nham)
  bat_truoc_review_cheo   = da_sua / (da_sua + nguoi_tim)       (% loi duoc tool bat truoc khi nguoi review cheo)
  so_vong_tra_lai         = so lan review co day Issue (moi lan = job bi tra ve annotator 1 vong)
"""
import json
import os
from datetime import datetime

import review_core as R

POINT_TOL = 1.0      # px: toa do doi it hon muc nay coi nhu khong sua
NEW_IOU = 0.3        # Issue "thieu": vat moi trung vi tri Issue >= muc nay -> da bo sung


def _box(points, kind="rectangle"):
    p = [float(v) for v in points]
    if kind == "mask":
        return [p[-4], p[-3], p[-2] + 1, p[-1] + 1]
    if kind == "rectangle":
        return R._rect(p)
    return [min(p[0::2]), min(p[1::2]), max(p[0::2]), max(p[1::2])]


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix
    return ix / u if u > 0 else 0.0


def _attrs(x):
    return sorted((a.get("spec_id"), str(a.get("value"))) for a in x.get("attributes") or [])


def _same_shape(a, b):
    if a.get("label_id") != b.get("label_id") or a.get("type") != b.get("type") or _attrs(a) != _attrs(b):
        return False
    if bool(a.get("occluded")) != bool(b.get("occluded")) or bool(a.get("outside")) != bool(b.get("outside")):
        return False
    pa, pb = a.get("points") or [], b.get("points") or []
    if len(pa) != len(pb):
        return False
    return all(abs(float(x) - float(y)) <= POINT_TOL for x, y in zip(pa, pb))


def _index(ann):
    return ({s["id"]: s for s in ann.get("shapes", [])}, {t["id"]: t for t in ann.get("tracks", [])})


def _track_same(a, b, frame):
    if a.get("label_id") != b.get("label_id") or _attrs(a) != _attrs(b):
        return False
    ka = {k["frame"]: k for k in a.get("shapes", [])}
    kb = {k["frame"]: k for k in b.get("shapes", [])}
    if set(ka) != set(kb):
        return False                    # them / bot keyframe (vd sua tai frame bi bao)
    return all(_same_shape(dict(ka[f], label_id=0), dict(kb[f], label_id=0)) for f in ka)


def outcome(fp, issue_box, before, after):
    """'da_sua' | None (nhan khong doi) cho 1 Issue tool. fp = 'frame|kind|ref'."""
    try:
        frame, kind, ref = fp.split("|", 2)
        frame = int(frame)
    except ValueError:
        return None
    bs, bt = _index(before)
    as_, at = _index(after)
    if ref.startswith("shape "):
        sid = int(ref.split()[1])
        if sid not in bs:
            return None
        if sid not in as_ or not _same_shape(bs[sid], as_[sid]):
            return "da_sua"
        return None
    if ref.startswith("track "):
        tid = int(ref.split()[1])
        if tid not in bt:
            return None
        if tid not in at or not _track_same(bt[tid], at[tid], frame):
            return "da_sua"
        return None
    if ref.startswith("@") or ref == "None":           # bao thieu: co vat moi o dung cho
        new_s = [s for i, s in as_.items() if i not in bs and s["frame"] == frame]
        for s in new_s:
            if _iou(_box(s["points"], s.get("type", "rectangle")), issue_box) >= NEW_IOU:
                return "da_sua"
        for i, t in at.items():
            ks = [k for k in t.get("shapes", []) if k["frame"] == frame and not k.get("outside")]
            if (i not in bt or len(t.get("shapes", [])) != len(bt[i].get("shapes", []))) and ks:
                if _iou(_box(ks[0]["points"], ks[0].get("type", "rectangle")), issue_box) >= NEW_IOU:
                    return "da_sua"
        return None
    return None                                         # ghi chu tay / tong ket: khong do


def _ts(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _baselines(runs):
    """fingerprint -> [(gio chay, run_id, chi so finding, annotations luc review, finding)] cua moi lan review da day Issue."""
    out = {}
    for r in sorted(runs, key=lambda r: r["id"]):
        if not r.get("pushed") or not r.get("out_dir"):
            continue
        try:
            res = json.load(open(os.path.join(r["out_dir"], "ket_qua_review.json"), encoding="utf-8"))
            before = json.load(open(os.path.join(r["out_dir"], "annotations_truoc_review.json"), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for i, f in enumerate(res.get("findings", [])):
            if f.get("frame") is None:
                continue
            out.setdefault(R.Review.fingerprint(f), []).append((r["created"], r["id"], i, before, f))
    return out


def _pick(cands, issue_time):
    """Lan review gan nhat TRUOC luc Issue duoc tao (nhan luc do = nhan annotator thay khi nhan Issue)."""
    if not cands:
        return None
    if issue_time is None:
        return cands[0]
    ok = [c for c in cands if c[0] < issue_time]          # lan review luon duoc tao truoc khi day Issue
    return ok[-1] if ok else None


def job_effect(cv, job_id, runs, feedback):
    """cv: review_core.Cvat. runs: cac lan review cua job (store.list_runs). feedback: {run_id: {finding_id: {...}}}.
    Tra ve dict chi so + danh sach Issue da phan loai."""
    base = _baselines(runs)
    after = cv.annotations(job_id)
    rows, human = [], 0
    for it in cv.issues(job_id):
        first = cv.first_comment(it["id"])
        ti = R.tool_issue(first)
        if ti is None:
            human += 1                  # nguoi review tu tao: loi tool bo sot
            continue
        if not ti[0] or "|tong_ket|" in ti[0] or "|ghi_chu|" in ti[0]:
            continue
        pos = it.get("position") or []
        ib = [min(pos[0::2]), min(pos[1::2]), max(pos[0::2]), max(pos[1::2])] if len(pos) >= 4 else [0, 0, 0, 0]
        # 1 Issue co the gop nhieu loi cua cung 1 vat ([qc:fp1;fp2]) -> moi loi 1 dong, de % dung theo loai van chinh xac
        for fp in ti[0].split(";"):
            c = _pick(base.get(fp), _ts(it.get("created_date")))
            b = (c[1], c[2], c[3], c[4]) if c else None
            res = outcome(fp, ib, b[2], after) if b else None
            if b is None:
                res = "khong_ro"
            elif res is None:
                if (feedback.get(b[0]) or {}).get(b[1], {}).get("verdict") == "tool_nham":
                    res = "tool_nham"
                elif it.get("resolved"):
                    res = "khong_sua"
                else:
                    res = "chua_xu_ly"
            kind = fp.split("|")[1]
            rows.append(dict(issue=it["id"], frame=it.get("frame"), kind=kind, kind_vi=R.KIND_VI.get(kind, kind),
                             ket_qua=res, msg=(b[3]["msg"] if b else ti[1])[:160], sure=(b[3].get("sure") if b else None)))
    # loi danh "tool nham" tren web nen khong duoc day len: van la bao nham cua tool
    for fp, cands in base.items():
        _, rid, i, _, f = cands[0]
        if (feedback.get(rid) or {}).get(i, {}).get("verdict") == "tool_nham":
            rows.append(dict(issue=None, frame=f.get("frame"), kind=f["kind"], kind_vi=R.KIND_VI.get(f["kind"], f["kind"]),
                             ket_qua="tool_nham", msg=f["msg"][:160], sure=f.get("sure")))
    c = {k: sum(r_["ket_qua"] == k for r_ in rows) for k in ("da_sua", "khong_sua", "tool_nham", "chua_xu_ly", "khong_ro")}
    judged = c["da_sua"] + c["khong_sua"] + c["tool_nham"]
    by_kind = {}
    for r_ in rows:
        d = by_kind.setdefault(r_["kind_vi"], dict(da_sua=0, khong_sua=0, tool_nham=0, chua_xu_ly=0, khong_ro=0))
        d[r_["ket_qua"]] += 1
    rounds = sum(1 for r in runs if r.get("pushed") and (r["pushed"].get("created", 0) + r["pushed"].get("kept", 0)) > 0)
    return dict(job_id=job_id, **c, nguoi_tim=human, so_issue_tool=len(rows),
                ti_le_issue_dung=c["da_sua"] / judged if judged else None,
                bat_truoc_review_cheo=c["da_sua"] / (c["da_sua"] + human) if judged and (c["da_sua"] + human) else None,
                so_vong_tra_lai=rounds, so_lan_review=len(runs), theo_loai=by_kind, issues=rows)


def summary(items):
    """Gop nhieu job -> chi so tong."""
    t = {k: sum(x[k] for x in items) for k in ("da_sua", "khong_sua", "tool_nham", "chua_xu_ly", "khong_ro", "nguoi_tim")}
    judged = t["da_sua"] + t["khong_sua"] + t["tool_nham"]
    by_kind = {}
    for x in items:
        for k, d in x["theo_loai"].items():
            s = by_kind.setdefault(k, dict(da_sua=0, khong_sua=0, tool_nham=0, chua_xu_ly=0, khong_ro=0))
            for kk, v in d.items():
                s[kk] += v
    return dict(**t, jobs=len(items),
                ti_le_issue_dung=t["da_sua"] / judged if judged else None,
                bat_truoc_review_cheo=t["da_sua"] / (t["da_sua"] + t["nguoi_tim"]) if judged and (t["da_sua"] + t["nguoi_tim"]) else None,
                vong_tra_lai_tb=sum(x["so_vong_tra_lai"] for x in items) / len(items) if items else None,
                theo_loai={k: dict(v, ti_le_dung=(v["da_sua"] / (v["da_sua"] + v["khong_sua"] + v["tool_nham"])
                                                   if v["da_sua"] + v["khong_sua"] + v["tool_nham"] else None))
                           for k, v in by_kind.items()},
                per_job=[{k: v for k, v in x.items() if k not in ("issues", "theo_loai")} for x in items])
