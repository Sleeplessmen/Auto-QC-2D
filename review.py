"""
review.py — Review nhan 2D bang lenh (giong trang web review_web.py, chung 1 bo nao review_core.py).

  review.bat                                lay CVAT_URL / CVAT_TOKEN / CVAT_TASK_ID / CVAT_JOB_ID trong .env,
                                            review + day Issue len CVAT (doi job khac = sua .env)
  review.bat --job 57                       job khac voi .env (URL/token van lay trong .env)
  review.bat --env .env.class               dung file cau hinh khac (vd CVAT localhost)
  review.bat --job 57 --khong-day           chi danh gia, khong day
  review.bat --file job57.zip               chi danh gia file export (khong day)
"""
import argparse
import os
import sys

from dotenv import dotenv_values

import review_core as R


def main():
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", type=int)
    ap.add_argument("--task", type=int)
    ap.add_argument("--file", help="file export .zip (CVAT for images 1.1 / COCO / YOLO)")
    ap.add_argument("--env", default=".env", help="file chua CVAT_URL, CVAT_TOKEN, CVAT_TASK_ID, CVAT_JOB_ID (mac dinh .env)")
    ap.add_argument("--url")
    ap.add_argument("--token")
    ap.add_argument("--nhanh", action="store_true", help="che do nhanh cho may yeu (kem chinh xac hon)")
    ap.add_argument("--khong-nguoi-lai", action="store_true", help="job khong gan box person cho nguoi lai xe may")
    ap.add_argument("--khong-day", action="store_true", help="chi danh gia, khong day Issue")
    ap.add_argument("--chi-loi-chac", action="store_true", help="chi day ghi chu tool chac chan (bo 'khong chac')")
    ap.add_argument("--giu-issue-cu", action="store_true", help="khong xoa Issue tu dong cua lan truoc")
    ap.add_argument("--so-frame", type=int, help="chi chay N frame dau (thu nhanh)")
    args = ap.parse_args()
    env = dotenv_values(os.path.join(R.HERE, args.env)) if os.path.exists(os.path.join(R.HERE, args.env)) else {}
    url = args.url or env.get("CVAT_URL")
    token = args.token or env.get("CVAT_TOKEN")
    num = lambda v: int(v) if str(v or "").strip().isdigit() else None
    job = args.job or (None if args.file else num(env.get("CVAT_JOB_ID")))
    task = args.task or (num(env.get("CVAT_TASK_ID")) if job and not args.job else None)   # task trong .env chi di kem job trong .env
    if not job and not args.file:
        ap.error(f"can --job, --file hoac CVAT_JOB_ID trong {args.env}")
    if job:
        print(f"CVAT: {url} | task {task or '?'} | job {job} (cau hinh: {args.env})")
    rv = R.Review()
    st = rv.run(url=url, token=token, task_id=task, job_id=job, zip_path=args.file,
                mode="nhanh" if args.nhanh else "chinh_xac", rider_person=not args.khong_nguoi_lai, max_frames=args.so_frame)
    print(f"\n{st['frames']} anh, {st['boxes']} box | box khong co loi chac chan: {st['ok']} ({st['ok'] / max(1, st['boxes']):.1%}) "
          f"| {st['sure']} loi, {st['unsure']} khong chac | {st['giay'] / 60:.1f} phut")
    print(f"Ket qua: {rv.out_dir}")
    if job and not args.khong_day:
        rv.push(include_unsure=not args.chi_loi_chac, replace_old=not args.giu_issue_cu)


if __name__ == "__main__":
    main()
