"""Chinh nguong seg_check tren dac trung da thu bang seg_thu_dac_trung.py:  python seg_chinh_nguong.py <feats.json>"""
import json, sys, itertools
rows = json.load(open(sys.argv[1]))
KINDS = ["co", "phinh", "lech", "mat_phan", "tho"]


def pick(r, wrong=0.2):
    t, p = r.get("t"), r.get("p")
    if t is not None and t["iou"] >= wrong:
        return t, p
    return p, None


def bad_area(m, A, P, iou_ok):
    return m["iou"] < iou_ok and ((m["lem"] >= A and m["lem_px"] >= P) or (m["thua"] >= A and m["thua_px"] >= P))


def bad_ring(m, Rr, Rpx, F, iou_ok):
    sd = m["sd_med"]
    if m["iou"] >= iou_ok or abs(m["sd_med_px"]) < Rpx or abs(sd) < Rr:
        return False
    return (m["out_frac"] if sd > 0 else m["in_frac"]) >= F


def decide(r, P):
    main, alt = pick(r)
    if main is None:
        return 0
    f = bad_area(main, P["A"], P["Ppx"], P["iou_ok"]) or (P["ring"] and bad_ring(main, P["Rr"], P["Rpx"], P["F"], P["iou_ok"]))
    if not f:
        return 0
    sev = max(main["lem"], main["thua"]) >= P["As"] or (P["ring"] and bad_ring(main, P["Rr"] * 1.5, P["Rpx"] * 1.5, P["F"], P["iou_ok"]))
    alt_ok = alt is None or bad_area(alt, P["A"], P["Ppx"], P["iou_ok"]) or (P["ring"] and bad_ring(alt, P["Rr"], P["Rpx"], P["F"], P["iou_ok"]))
    sure = sev and main["sc"] >= 0.85 and r["side"] >= P["side"] and alt_ok
    return 2 if sure else 1


def score(P):
    clean = [r for r in rows if r["kind"] == "dung"]
    fs = sum(decide(r, P) == 2 for r in clean) / len(clean) * 100
    fu = sum(decide(r, P) == 1 for r in clean) / len(clean) * 100
    rec, recs = {}, {}
    for k in KINDS:
        e = [r for r in rows if r["kind"] == k]
        d = [decide(r, P) for r in e]
        rec[k] = sum(x > 0 for x in d) / max(1, len(e))
        recs[k] = sum(x == 2 for x in d) / max(1, len(e))
    allr = [r for r in rows if r["kind"] != "dung"]
    d = [decide(r, P) for r in allr]
    return fs, fu, sum(x > 0 for x in d) / len(allr), sum(x == 2 for x in d) / len(allr), rec, recs


base = dict(A=0.12, As=0.20, Ppx=150, iou_ok=0.80, ring=False, Rr=0.04, Rpx=2.0, F=0.6, side=48)
print("n clean", sum(r["kind"] == "dung" for r in rows), "n err", sum(r["kind"] != "dung" for r in rows))
fs, fu, R, Rs, rec, recs = score(base)
print(f"BASE  fp chac {fs:.1f} kc {fu:.1f} | bat {R:.1%} chac {Rs:.1%} |", {k: f"{rec[k]:.0%}/{recs[k]:.0%}" for k in KINDS})
res = []
for A, As, Ppx, iou_ok, ring, Rr, Rpx, F, side in itertools.product([0.10, 0.12, 0.15], [0.18, 0.22, 0.28], [60, 100, 150],
                                                                  [0.75, 0.80, 0.85], [False, True], [0.03, 0.05], [1.5, 2.5],
                                                                  [0.6, 0.75], [40, 64]):
    if not ring and (Rr, Rpx, F) != (0.03, 1.5, 0.6):
        continue
    P = dict(A=A, As=As, Ppx=Ppx, iou_ok=iou_ok, ring=ring, Rr=Rr, Rpx=Rpx, F=F, side=side)
    fs, fu, R, Rs, rec, recs = score(P)
    res.append((fs, fu, R, Rs, P, rec, recs))
for cap_s, cap_t in ((1.0, 6.0), (1.5, 8.0), (2.0, 10.0)):
    ok = [x for x in res if x[0] <= cap_s and x[0] + x[1] <= cap_t]
    ok.sort(key=lambda x: (-(x[2] + x[3]), x[0]))
    print(f"\n== fp chac <= {cap_s}, tong fp <= {cap_t}: {len(ok)} bo")
    for fs, fu, R, Rs, P, rec, recs in ok[:4]:
        print(f"  fp chac {fs:.1f} kc {fu:.1f} | bat {R:.1%} chac {Rs:.1%} | {P}")
        print("     ", {k: f"{rec[k]:.0%}/{recs[k]:.0%}" for k in KINDS})
