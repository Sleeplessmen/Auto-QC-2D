"""Gom ket qua do do chinh xac cua tool (review_eval.py --json, test e2e) -> static/do_tin_cay.json cho trang "Độ tin cậy".

    venv\\Scripts\\python cvat_2d\\web_qc\\tao_do_tin_cay.py --bdd-new test_new.json --bdd-old test_old.json \\
        --vn-new data_new.json --vn-old box_eval.json --seg seg_eval.json

Moi file la ket qua `review_eval.py --json`. Thieu file nao thi bo qua phan do. Test e2e lay tu artifacts/e2e.
"""
import argparse
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(os.path.dirname(HERE), "apps", "web", "static")
E2E = os.path.join(os.path.dirname(HERE), "artifacts", "e2e")


def load(p):
    if p and os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    return None


def box_block(d):
    """1 nhom ket qua review_eval (box) -> so lieu gon cho trang web."""
    if not d:
        return None
    n_err = sum(v["tong"] for v in d["theo_loai"].values())
    tp = d["bat_chac"] * n_err                                  # loi that tool bao "chac chan"
    fp = d["bao_nham_chac_100box"] * d["box"] / 100              # bao nham "chac chan" tren nhan dung
    return dict(anh=d["anh"], box=d["box"], loi_cai=n_err, bat=d["bat_loi"], bat_chac=d["bat_chac"],
                bao_nham_chac=d["bao_nham_chac_100box"], bao_nham_kc=d["bao_nham_kc_100box"],
                issue_chac_dung=tp / (tp + fp) if tp + fp else None, sach_dung=d["cho_qua_tu_dong_dung"],
                theo_loai={k: dict(tong=v["tong"], chac=v["chac"], khong_chac=v["khong_chac"]) for k, v in d["theo_loai"].items()})


def by_cond(d):
    return {k.split(": ", 1)[1]: box_block(v) for k, v in (d or {}).items() if k.startswith(("luc: ", "troi: "))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bdd-new"); ap.add_argument("--bdd-old")
    ap.add_argument("--vn-new"); ap.add_argument("--vn-old")
    ap.add_argument("--seg")
    ap.add_argument("--out", default=os.path.join(STATIC_DIR, "do_tin_cay.json"))
    a = ap.parse_args()
    bn, bo, vn, vo, sg = map(load, (a.bdd_new, a.bdd_old, a.vn_new, a.vn_old, a.seg))
    out = dict(ngay=time.strftime("%Y-%m-%d"), bo_du_lieu={}, dieu_kien={}, e2e={})
    if bn:
        out["bo_du_lieu"]["bdd"] = dict(ten="BDD100K (335 ảnh giữ riêng, vật từ 10 px)",
                                        moi=box_block(bn["tat ca"]), cu=box_block(bo["tat ca"]) if bo else None)
        out["dieu_kien"] = dict(moi=by_cond(bn), cu=by_cond(bo))
    if vn:
        out["bo_du_lieu"]["vn"] = dict(ten="Ảnh đường phố Việt Nam (123 ảnh D:\\DATA)",
                                       moi=box_block(vn["tat ca"]), cu=box_block(vo["tat ca"]) if vo else None)
    if sg:
        out["seg"] = dict(anh=sg["anh"], polygon=sg["polygon_cham"], loi_cai=sg["loi_cai"], bat=sg["bat_loi"], bat_chac=sg["bat_chac"],
                          bao_nham_chac=sg["bao_nham_chac_100"], bao_nham_kc=sg["bao_nham_kc_100"],
                          theo_loai=sg["theo_loai"], theo_co=sg.get("theo_co", {}))
    for k, f in (("bdd", "e2e_result.json"), ("id", "e2e_id.json"), ("track", "e2e_track.json")):
        d = load(os.path.join(E2E, f))
        if d:
            res = d.get("caught") or d.get("ket_qua") or {}
            out["e2e"][k] = dict(dat=sum(1 for v in res.values() if v), tong=len(res), chi_tiet=res,
                                 hieu_qua=(d.get("effect") or {}).get("ti_le_issue_dung"),
                                 ngay=time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(os.path.join(E2E, f)))))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Da ghi", a.out)


if __name__ == "__main__":
    main()
