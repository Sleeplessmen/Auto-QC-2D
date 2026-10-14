"""
store.py — Luu tru cua web QC (SQLite): nguoi dung, lan review, guideline, guideline gan cho task.
"""
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DB_PATH = os.path.join(DATA, "web_qc.db")
_lock = threading.Lock()

SCHEMA = """
create table if not exists users(
  username text primary key, pw text not null, role text not null default 'qc', created real);
create table if not exists runs(
  id integer primary key autoincrement, job_id integer, task_id integer, username text,
  status text, created real, started real, finished real, params text, stats text,
  out_dir text, guideline_id integer, error text, pushed text);
create table if not exists guidelines(
  id integer primary key autoincrement, name text, file_name text, file_path text,
  text text, rules text, created real, username text);
create table if not exists task_guideline(task_id integer primary key, guideline_id integer);
"""


def conn():
    os.makedirs(DATA, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, conn() as c:
        c.executescript(SCHEMA)
        # lan review dang chay khi tat web -> danh dau loi (worker khong con)
        c.execute("update runs set status='loi', error='Web bị tắt khi đang chạy' where status in ('cho','dang_chay')")
        if not c.execute("select 1 from users where role='admin'").fetchone():
            pw = os.environ.get("WEB_QC_ADMIN_PASSWORD") or secrets.token_urlsafe(9)
            c.execute("insert or replace into users values(?,?,?,?)", ("admin", hash_pw(pw), "admin", time.time()))
            path = os.path.join(DATA, "MAT_KHAU_ADMIN.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"Tai khoan: admin\nMat khau: {pw}\n(Dang nhap xong vao Cai dat doi mat khau roi xoa file nay.)\n")
            print(f"Da tao tai khoan admin. Mat khau o: {path}", flush=True)


# ---------------------------------------------------------------- nguoi dung
def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()


def check_pw(username, pw):
    with conn() as c:
        r = c.execute("select * from users where username=?", (username,)).fetchone()
    if not r:
        return None
    salt = r["pw"].split("$", 1)[0]
    return dict(r) if secrets.compare_digest(hash_pw(pw, salt), r["pw"]) else None


def users():
    with conn() as c:
        return [dict(username=r["username"], role=r["role"]) for r in c.execute("select * from users order by username")]


def set_user(username, pw=None, role=None):
    with _lock, conn() as c:
        old = c.execute("select * from users where username=?", (username,)).fetchone()
        if old is None and not pw:
            raise ValueError("Tài khoản mới phải có mật khẩu.")
        c.execute("insert or replace into users values(?,?,?,?)",
                  (username, hash_pw(pw) if pw else old["pw"], role or (old["role"] if old else "qc"),
                   old["created"] if old else time.time()))


def del_user(username):
    with _lock, conn() as c:
        c.execute("delete from users where username=?", (username,))


# ---------------------------------------------------------------- lan review
def _row(r):
    if r is None:
        return None
    d = dict(r)
    for k in ("params", "stats", "pushed"):
        d[k] = json.loads(d[k]) if d.get(k) else None
    return d


def new_run(job_id, task_id, username, params, guideline_id):
    with _lock, conn() as c:
        cur = c.execute("insert into runs(job_id,task_id,username,status,created,params,guideline_id) values(?,?,?,?,?,?,?)",
                        (job_id, task_id, username, "cho", time.time(), json.dumps(params), guideline_id))
        return cur.lastrowid


def update_run(run_id, **kw):
    for k in ("params", "stats", "pushed"):
        if k in kw and kw[k] is not None:
            kw[k] = json.dumps(kw[k], ensure_ascii=False)
    with _lock, conn() as c:
        c.execute(f"update runs set {', '.join(k + '=?' for k in kw)} where id=?", (*kw.values(), run_id))


def get_run(run_id):
    with conn() as c:
        return _row(c.execute("select * from runs where id=?", (run_id,)).fetchone())


def list_runs(limit=200, job_id=None):
    with conn() as c:
        if job_id:
            rs = c.execute("select * from runs where job_id=? order by id desc limit ?", (job_id, limit))
        else:
            rs = c.execute("select * from runs order by id desc limit ?", (limit,))
        return [_row(r) for r in rs]


# ---------------------------------------------------------------- guideline
def add_guideline(name, file_name, file_path, text, rules, username):
    with _lock, conn() as c:
        cur = c.execute("insert into guidelines(name,file_name,file_path,text,rules,created,username) values(?,?,?,?,?,?,?)",
                        (name, file_name, file_path, text, rules, time.time(), username))
        return cur.lastrowid


def update_guideline(gid, **kw):
    with _lock, conn() as c:
        c.execute(f"update guidelines set {', '.join(k + '=?' for k in kw)} where id=?", (*kw.values(), gid))


def get_guideline(gid):
    if not gid:
        return None
    with conn() as c:
        r = c.execute("select * from guidelines where id=?", (gid,)).fetchone()
    return dict(r) if r else None


def list_guidelines():
    with conn() as c:
        out = [dict(id=r["id"], name=r["name"], file_name=r["file_name"], created=r["created"], username=r["username"],
                    has_rules=bool((r["rules"] or "").strip()), n_chars=len(r["text"] or ""))
               for r in c.execute("select * from guidelines order by id desc")]
        tg = {r["task_id"]: r["guideline_id"] for r in c.execute("select * from task_guideline")}
    for g in out:
        g["tasks"] = sorted(t for t, gid in tg.items() if gid == g["id"])
    return out


def del_guideline(gid):
    with _lock, conn() as c:
        c.execute("delete from guidelines where id=?", (gid,))
        c.execute("delete from task_guideline where guideline_id=?", (gid,))


def set_task_guideline(task_id, gid):
    with _lock, conn() as c:
        if gid:
            c.execute("insert or replace into task_guideline values(?,?)", (task_id, gid))
        else:
            c.execute("delete from task_guideline where task_id=?", (task_id,))


def task_guideline(task_id):
    if not task_id:
        return None
    with conn() as c:
        r = c.execute("select guideline_id from task_guideline where task_id=?", (task_id,)).fetchone()
    return r["guideline_id"] if r else None
