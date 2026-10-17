"""Kiem tra loi ID cua track (job video): tool tu dung track rieng (noi vat detector thay qua cac khung bang vi tri +
hinh dang CLIP), roi doi chieu voi ID cua annotator — giong chi so IDSW cua bai toan MOT.

Loi bat duoc (ghi chu dat o khung xay ra loi):
  - doi_vat   : track annotator dang theo vat X thi chuyen sang vat Y, trong khi X van con ngay do (ID switch)
  - trao_id   : 2 track tra vat cho nhau o cung 1 khung (ID swap, vd 2 xe di cat qua nhau)
  - mot_vat_2_id : 1 vat bi tach thanh 2 track noi tiep (tool theo vat lien tuc), ke ca khi vat da di cho khac
  - hai_id_1_vat : 2 track cung luc nam tren 1 vat
  - ket_thuc_som : track da het (outside) ma vat van con trong anh nhieu khung
Ghi chu "thieu" lap lai tren cung 1 vat qua nhieu khung duoc gop lai thanh 1.
Khong sua nhan. Thieu bang chung chac chan (tool mat dau vat, vat bi che) -> "khong chac" hoac bo qua.
"""
import numpy as np
from scipy.optimize import linear_sum_assignment

ASSOC_IOU = 0.2         # noi vat tool giua 2 khung: IoU toi thieu (hoac rat giong ve hinh)
ASSOC_SIM = 0.80        # cosine CLIP toi thieu khi IoU thap (vat di nhanh)
MAX_GAP = 3             # tool mat dau vat toi 3 khung van noi lai
MATCH_IOU = 0.5         # box annotator <-> vat tool cung khung
MIN_RUN = 2             # 1 doan theo cung vat phai dai >= 2 khung moi tinh (tranh nhieu 1 khung)
SAME_IOU = 0.3          # box annotator sau khi doi va vat cu: IoU < muc nay -> that su da roi vat cu
APPEAR_DROP = 0.72      # cosine hinh track truoc/sau < muc nay -> hinh vat doi han
DUP_FRAMES = 2          # 2 track cung 1 vat >= 2 khung
EARLY_FRAMES = 3        # vat con >= 3 khung sau khi track het
# dong bo kich thuoc: ti le (box annotator / box vat tool thay) phai gan nhu khong doi suot track (vat lai gan / ra xa thi
# ca 2 cung doi nen ti le giu nguyen). Khung lech ti le > 20% (va >= 6px) so voi trung vi cua track -> lech kich thuoc
SIZE_TOL = 0.20
SIZE_SURE = 0.35
SIZE_PX = 6
SPIKE_TOL = 0.30        # khong co vat tool: 1 keyframe lech > 30% so voi trung binh 2 keyframe 2 ben (2 ben gan bang nhau)


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix
    return ix / u if u > 0 else 0.0


def _inside(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix / max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))


def embed(clf, img, boxes):
    """vector hinh (CLIP, da chuan hoa) cho tung box"""
    if clf is None or not boxes:
        return [None] * len(boxes)
    import torch
    with torch.no_grad():
        f = clf._image(img, [list(map(float, b)) for b in boxes], 0.05)
    return [v for v in f.float().cpu().numpy()]


def _sim(a, b):
    return float(a @ b) if a is not None and b is not None else 0.0


class Collector:
    """Gom du lieu tung khung trong luc review (review_core.run), phan tich o cuoi."""

    def __init__(self, clf, job_group):
        self.clf, self.job_group = clf, job_group
        self.frames = []            # [(frame, [tool obj], [labeler track box])]

    def add(self, n, img, tool, lab, group_of):
        T = [dict(box=list(o["box"]), grp=group_of(o["cls"]), score=float(o["score"]),
                  sure=o.get("trang_thai") == "TU_DONG") for o in tool if group_of(o["cls"])]
        Lb = [dict(ref=l["id"], label=l["label"], grp=self.job_group.get(l["label"]), box=list(l["box"]),
                   occ=bool(l.get("occluded")), key=bool(l.get("keyframe", True)))
              for l in lab if str(l["id"]).startswith("track ")]
        if not Lb:
            self.frames.append((n, T, Lb))
            return
        E = embed(self.clf, img, [o["box"] for o in T] + [l["box"] for l in Lb])
        for o, e in zip(T, E[:len(T)]):
            o["emb"] = e
        for l, e in zip(Lb, E[len(T):]):
            l["emb"] = e
        self.frames.append((n, T, Lb))

    def has_tracks(self):
        return any(Lb for _, _, Lb in self.frames)

    # ------------------------------------------------------------------ 1. tool tu dung track
    def _tool_tracks(self):
        active, nid = [], 0                          # [dict(id, box, emb, last, grp)]
        for k, (n, T, _) in enumerate(self.frames):
            live = [a for a in active if k - a["last"] <= MAX_GAP]
            cost = np.full((len(live), len(T)), 9.0)
            for i, a in enumerate(live):
                for j, o in enumerate(T):
                    if a["grp"] != o["grp"]:
                        continue
                    v, s = _iou(a["box"], o["box"]), _sim(a["emb"], o.get("emb"))
                    if v >= ASSOC_IOU or (s >= ASSOC_SIM and v > 0):
                        cost[i, j] = 1 - (0.6 * v + 0.4 * s)
            used = set()
            if len(live) and len(T):
                for i, j in zip(*linear_sum_assignment(cost)):
                    if cost[i, j] < 9:
                        a, o = live[i], T[j]
                        o["tid"] = a["id"]
                        a.update(box=o["box"], last=k, emb=o.get("emb") if o.get("emb") is not None else a["emb"])
                        used.add(j)
            for j, o in enumerate(T):
                if j not in used:
                    nid += 1
                    o["tid"] = nid
                    active.append(dict(id=nid, box=o["box"], emb=o.get("emb"), last=k, grp=o["grp"]))

    # ------------------------------------------------------------------ 2. doi chieu ID annotator voi track cua tool
    def analyze(self):
        """-> {frame: [finding]}"""
        if not self.has_tracks():
            return {}
        self._tool_tracks()
        seq = {}                                     # ref -> [(k, frame, label, box, emb, tid | None)]
        meta = {}                                    # (ref, k) -> (bi che, la keyframe)
        tool_at = {}                                 # (k, tid) -> obj
        for k, (n, T, Lb) in enumerate(self.frames):
            for o in T:
                tool_at[(k, o["tid"])] = o
            pairs = sorted(((_iou(l["box"], o["box"]), i, j) for i, l in enumerate(Lb) for j, o in enumerate(T)
                            if l["grp"] == o["grp"]), reverse=True)
            ml, mt = {}, set()
            for v, i, j in pairs:
                if v < MATCH_IOU:
                    break
                if i not in ml and j not in mt:
                    ml[i] = T[j]["tid"]
                    mt.add(j)
            for i, l in enumerate(Lb):          # box chua ghep: cho ghep vao vat da co track khac (2 ID tren 1 vat)
                if i not in ml:
                    cand = [(_iou(l["box"], o["box"]), o["tid"]) for o in T if o["grp"] == l["grp"]]
                    v, t = max(cand, default=(0, None))
                    if v >= MATCH_IOU:
                        ml[i] = t
            for i, l in enumerate(Lb):
                seq.setdefault(l["ref"], []).append((k, n, l["label"], l["box"], l.get("emb"), ml.get(i)))
                meta[(l["ref"], k)] = (l["occ"], l["key"])
        out = {}

        def add(k, f):
            out.setdefault(self.frames[k][0], []).append(f)

        def runs(s):
            """doan lien tiep cung 1 vat tool: [(tid, k dau, k cuoi, so khung)]"""
            r = []
            for k, _, _, _, _, tid in s:
                if tid is None:
                    continue
                if r and r[-1][0] == tid:
                    r[-1] = (tid, r[-1][1], k, r[-1][3] + 1)
                else:
                    r.append((tid, k, k, 1))
            return [x for x in r if x[3] >= MIN_RUN]

        R = {ref: runs(s) for ref, s in seq.items()}
        switches = {}                                # ref -> [(k doi, tid cu, tid moi)]
        for ref, rs in R.items():
            s = {k: x for k, *x in seq[ref]}
            for i, a in enumerate(rs):
                # track roi vat dang theo (doan a ket thuc) ma track van con o khung ke tiep
                k = a[2] + 1
                if k not in s:
                    continue
                b = rs[i + 1] if i + 1 < len(rs) else None
                if b is not None and b[0] == a[0]:
                    continue                          # quay lai dung vat cu (tool mat dau 1 doan): khong phai doi vat
                box_k = s[k][2]
                new_tid = s[k][4]
                # vat cu con o khung k? theo ID cua tool, hoac (tool mat ID vat cu) theo vi tri doan = box truoc + van toc
                p1 = s[k - 1][2]
                p0 = s[k - 2][2] if k - 2 in s else p1
                pred = [2 * u - v for u, v in zip(p1, p0)]
                grp = self.job_group.get(s[k][1])
                olds = [o for o in self.frames[k][1] if o["grp"] == grp and o["tid"] != new_tid
                        and (o["tid"] == a[0] or _iou(o["box"], pred) >= 0.4)]
                still = any(_iou(o["box"], box_k) < 0.5 and _iou(o["box"], pred) > _iou(box_k, pred) for o in olds) or \
                    any(o["tid"] == a[0] and _iou(o["box"], box_k) < SAME_IOU for o in olds)
                before = [x[3] for kk, x in s.items() if a[1] <= kk <= a[2] and x[3] is not None]
                after = [x[3] for kk, x in s.items() if kk >= k and x[3] is not None][:max(MIN_RUN, 3)]
                ap = _sim(np.mean(before, 0), np.mean(after, 0)) if before and after else 1.0
                if still or ap < APPEAR_DROP:
                    switches.setdefault(ref, []).append((k, a[0], b[0] if b else new_tid, still, ap))
        # tra ID giua 2 track
        done = set()
        for r1, sw1 in switches.items():
            for (k1, o1, n1, _, _) in sw1:
                for r2, sw2 in switches.items():
                    if r2 == r1 or (r2, r1) in done:
                        continue
                    for (k2, o2, n2, _, _) in sw2:
                        if abs(k1 - k2) <= 1 and o1 == n2 and n1 == o2:
                            done.add((r1, r2))
                            s1 = {k: x for k, *x in seq[r1]}
                            add(k1, dict(kind="track", sub="trao_id", sure=True, label=s1[k1][1], box=s1[k1][2], ref=r1,
                                         refs=[r1, r2], tang=2, msg=f"Tráo ID: từ khung {self.frames[k1][0]}, {r1} và {r2} đổi vật cho nhau "
                                                     f"(2 vật đi sát / cắt qua nhau). Mỗi track phải theo đúng 1 vật suốt video."))
        # tra ID khi tool khong thay vat ban dau cua track kia: K roi vat X dung luc track J (truoc do khong theo X)
        # bat dau theo X -> J da lay vat cu cua K
        for r1, sw1 in switches.items():
            if any(r1 in p for p in done):
                continue
            for (k1, o1, n1, still, _) in sw1:
                for r2, s2 in seq.items():
                    if r2 == r1 or any(r2 in p for p in done):
                        continue
                    took = [k for k, *_x, tid in s2 if tid == o1]
                    had = [k for k, *_x, tid in s2 if tid == o1 and k < k1 - 1]
                    if took and not had and min(took) in (k1 - 1, k1, k1 + 1) and len(took) >= MIN_RUN:
                        done.add((r1, r2))
                        s1 = {k: x for k, *x in seq[r1]}
                        add(k1, dict(kind="track", sub="trao_id", sure=still, label=s1[k1][1], box=s1[k1][2], ref=r1,
                                     refs=[r1, r2], tang=2,
                                     msg=f"{'Tráo' if still else 'Có thể tráo'} ID: tới khung {self.frames[k1][0]}, {r1} rời vật "
                                         f"đang theo, còn {r2} lại nhận đúng vật đó (2 vật đi sát / cắt qua nhau). "
                                         f"Mỗi track phải theo đúng 1 vật suốt video."))
                        break
        self.debug = dict(seq={r: [(x[0], x[5]) for x in v] for r, v in seq.items()}, runs=R, switches={r: [(k, o, n) for k, o, n, *_ in v] for r, v in switches.items()}, done=sorted(done))
        swapped = {r for pair in done for r in pair}
        for ref, sw in switches.items():
            if ref in swapped:
                continue
            s = {k: x for k, *x in seq[ref]}
            for k, o, nw, still, ap in sw:
                sure = still and ap < 0.85
                why = "vật cũ vẫn còn ngay bên cạnh" if still else f"hình vật khác hẳn trước (giống {ap * 100:.0f}%)"
                add(k, dict(kind="track", sub="doi_vat", sure=sure, label=s[k][1], box=s[k][2], ref=ref, tang=2,
                            msg=f"{'' if sure else 'Có thể '}{'Đổi' if sure else 'đổi'} vật (ID switch): {ref} '{s[k][1]}' "
                                f"đang theo 1 vật, tới khung {self.frames[k][0]} chuyển sang vật khác ({why}). "
                                f"Tách thành track mới cho vật này, track cũ tiếp tục theo vật cũ."))
        # 1 vat 2 ID (noi tiep) va 2 ID cung luc tren 1 vat
        span = {ref: (s[0][0], s[-1][0]) for ref, s in seq.items()}
        main = {}
        for ref, rs in R.items():
            if rs and ref not in switches:
                t = max(rs, key=lambda x: x[3])
                main[ref] = t[0]
        refs = sorted(main, key=lambda r: span[r][0])
        for i, a in enumerate(refs):
            for b in refs[i + 1:]:
                if main[a] != main[b]:
                    continue
                sa, sb = span[a], span[b]
                la, lb = seq[a][0][2], seq[b][0][2]
                if sa[1] < sb[0]:                    # noi tiep
                    k = sb[0]
                    box = next(x[3] for x in seq[b] if x[0] == k)
                    diff = f", và khác nhãn ('{la}' / '{lb}')" if la != lb else ""
                    add(k, dict(kind="track", sub="mot_vat_2_id", sure=True, label=lb, box=box, ref=b, tang=2,
                                msg=f"1 vật 2 ID: {b} là cùng vật với {a} (tool theo dõi vật này liên tục từ khung "
                                    f"{self.frames[sa[0]][0]} tới {self.frames[sb[1]][0]}){diff}. Nối thành 1 track."))
                else:                                # trung thoi gian
                    ov = [k for k, *_r, tid in seq[a] if tid == main[a]
                          and any(kk == k and t2 == main[b] for kk, *_q, t2 in seq[b])]
                    if len(ov) >= DUP_FRAMES:
                        k = ov[0]
                        box = next(x[3] for x in seq[b] if x[0] == k)
                        add(k, dict(kind="track", sub="hai_id_1_vat", sure=True, label=lb, box=box, ref=b, tang=2,
                                    msg=f"2 ID trên 1 vật: {a} và {b} cùng nằm trên 1 vật ở {len(ov)} khung "
                                        f"(từ khung {self.frames[k][0]}). Xoá 1 track."))
        # track ket thuc som: vat tool van con sau khi track het
        covered = {(k, tid) for s in seq.values() for k, *_r, tid in s if tid is not None}
        joined = {f["ref"] for fs in out.values() for f in fs if f["sub"] == "mot_vat_2_id"}
        joined_first = {a for a in main for b in joined if main.get(a) == main.get(b) and a != b and span[a][0] < span[b][0]}
        for ref, tid in main.items():
            if ref in joined_first:
                continue                      # da bao "1 vat 2 ID" (noi 2 track lai la het thieu doan giua)
            last_k = span[ref][1]
            if last_k >= len(self.frames) - 1:
                continue
            more = [k for k in range(last_k + 1, len(self.frames))
                    if (k, tid) in tool_at and tool_at[(k, tid)]["sure"] and (k, tid) not in covered]
            if len(more) >= EARLY_FRAMES and more[0] == last_k + 1:
                end = more[0]
                while end + 1 in more:
                    end += 1
                o = tool_at[(more[0], tid)]
                add(more[0], dict(kind="track", sub="ket_thuc_som", sure=False, label=seq[ref][0][2], box=o["box"], ref=ref,
                                  tang=2, end_tid=tid,
                                  msg=f"Track kết thúc sớm: {ref} '{seq[ref][0][2]}' hết ở khung {self.frames[last_k][0]} "
                                      f"nhưng vật vẫn còn tới khung {self.frames[end][0]}. Kéo dài track (bỏ outside)."))
        # dong bo kich thuoc trong track
        bad_ref = {f["ref"] for fs in out.values() for f in fs if f["sub"] in ("doi_vat", "trao_id", "hai_id_1_vat")}
        for ref, s in seq.items():
            if ref in bad_ref:
                continue                              # da sai ID: kich thuoc theo vat khac la dung, khong bao them
            self._size_sync(ref, s, meta, tool_at, add)
        self.tool_at = tool_at
        self.debug_seq = {r: [(x[0], x[5]) for x in v] for r, v in seq.items()}
        return out

    def _size_sync(self, ref, s, meta, tool_at, add):
        hw = lambda b: (b[3] - b[1], b[2] - b[0])
        tids = [t for *_x, t in s if t is not None]
        main_tid = max(set(tids), key=tids.count) if tids else None
        rows = []
        for k, n, lb, box, _e, tid in s:
            occ, key = meta.get((ref, k), (False, True))
            o = tool_at.get((k, tid)) if tid is not None else None
            if o is None and main_tid is not None:
                # khung lech nhieu thi box khong con trung du de ghep: van so voi vat track dang theo o cac khung khac
                c = tool_at.get((k, main_tid))
                if c is not None and (_iou(c["box"], box) >= 0.25 or _inside(box, c["box"]) >= 0.8):
                    o = c
            if o is None or occ:
                continue
            (h, w), (th, tw) = hw(box), hw(o["box"])
            if th > 0 and tw > 0:
                rows.append((k, n, lb, box, h, w, h / th, w / tw, th, tw, key, o["sure"]))
        flagged = set()
        if len(rows) >= 3:
            mh, mw = float(np.median([r[6] for r in rows])), float(np.median([r[7] for r in rows]))
            dev = []
            for r in rows:
                k, n, lb, box, h, w, rh, rw, th, tw, key, sure_t = r
                eh, ew = mh * th, mw * tw                     # kich thuoc dung neu gan dong bo voi cac khung khac
                dh, dw = rh / mh - 1, rw / mw - 1
                bad_h = abs(dh) > SIZE_TOL and abs(h - eh) >= SIZE_PX
                bad_w = abs(dw) > SIZE_TOL and abs(w - ew) >= SIZE_PX
                if bad_h or bad_w:
                    dev.append((r, dh if bad_h else 0.0, dw if bad_w else 0.0, eh, ew))
            if dev and len(dev) <= len(rows) // 2:            # thieu so khung lech (da so khung la chuan cua track)
                groups = [[dev[0]]]                   # cac khung lech lien tiep -> 1 ghi chu
                for d in dev[1:]:
                    if d[0][0] == groups[-1][-1][0][0] + 1:
                        groups[-1].append(d)
                    else:
                        groups.append([d])
                for g in groups:
                    r0 = g[0][0]
                    worst = max(g, key=lambda d: max(abs(d[1]), abs(d[2])))
                    (k, n, lb, box, h, w, *_), dh, dw, eh, ew = worst[0], worst[1], worst[2], worst[3], worst[4]
                    parts = []
                    if dh:
                        parts.append(f"cao {h:.0f}px (các khung khác tương ứng ~{eh:.0f}px)")
                    if dw:
                        parts.append(f"rộng {w:.0f}px (~{ew:.0f}px)")
                    keys = [d[0][10] for d in g]
                    where = "keyframe vẽ lệch" if all(keys) else ("khung nội suy lệch, thêm keyframe" if not any(keys)
                                                                   else "keyframe / nội suy lệch")
                    fr = [d[0][1] for d in g]
                    sure = max(abs(dh), abs(dw)) > SIZE_SURE and all(d[0][11] for d in g)
                    flagged |= {d[0][0] for d in g}
                    add(r0[0], dict(kind="track", sub="kich_thuoc", sure=sure, label=lb, box=g[0][0][3], ref=ref, tang=2,
                                    frames=fr,
                                    msg=f"{'' if sure else 'Có thể '}{'Kích' if sure else 'kích'} thước track không đồng bộ "
                                        f"({where}): {ref} '{lb}' ở khung {fr[0]}" + (f"–{fr[-1]}" if len(fr) > 1 else "")
                                        + f" {', '.join(parts)}. Giữ cùng cách đóng box với các khung khác."))
        # khong du vat tool de so: 1 doan 1-3 keyframe lien tiep nhay kich thuoc so voi keyframe 2 ben (2 ben gan bang nhau)
        keyrows = [(k, n, lb, box) for k, n, lb, box, _e, _t in s if meta.get((ref, k), (False, True))[1]
                   and not meta.get((ref, k), (False, True))[0]]
        for L in (1, 2, 3):
            for i in range(1, len(keyrows) - L):
                left, mid, right = keyrows[i - 1], keyrows[i:i + L], keyrows[i + L]
                if any(m[0] in flagged for m in mid) or right[0] - left[0] > 6:
                    continue
                for d, nm in ((0, "cao"), (1, "rộng")):
                    a, b = hw(left[3])[d], hw(right[3])[d]
                    ref_v = (a + b) / 2
                    vs = [hw(m[3])[d] for m in mid]
                    if ref_v <= 0 or abs(a - b) / max(a, b) >= 0.15:
                        continue
                    if all(abs(v - ref_v) / ref_v > SPIKE_TOL and abs(v - ref_v) >= SIZE_PX for v in vs) and \
                            (all(v > ref_v for v in vs) or all(v < ref_v for v in vs)):
                        fr = [m[1] for m in mid]
                        add(mid[0][0], dict(kind="track", sub="kich_thuoc_nhay", sure=False, label=mid[0][2], box=mid[0][3],
                                            ref=ref, tang=2, frames=fr,
                                            msg=f"Có thể kích thước nhảy: {ref} '{mid[0][2]}' ở keyframe {fr[0]}"
                                                + (f"–{fr[-1]}" if len(fr) > 1 else "") + f" {nm} ~{np.mean(vs):.0f}px, "
                                                f"trong khi keyframe trước / sau ~{ref_v:.0f}px. Giữ kích thước đồng bộ trong track."))
                        flagged |= {m[0] for m in mid}
                        break

    def missing_tid(self, frame, box):
        """vat tool (track id) o khung `frame` trung box (de gop ghi chu 'thieu' cung 1 vat)"""
        k = next((i for i, (n, _, _) in enumerate(self.frames) if n == frame), None)
        if k is None:
            return None
        best = max(((_iou(o["box"], box), o["tid"]) for o in self.frames[k][1]), default=(0, None))
        return best[1] if best[0] >= 0.5 else None
