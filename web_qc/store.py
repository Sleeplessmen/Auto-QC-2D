"""
store.py — Luu tru cua web QC (SQLite): nguoi dung, ket noi CVAT, lan review, phan hoi "tool nham",
guideline, guideline gan cho task, cai dat chung.
Token CVAT duoc ma hoa khi luu (khoa rieng cua may chu trong data/secret.key) va khong bao gio tra ve trinh duyet.
"""
import base64
import hashlib
import hmac
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
create table if not exists connections(
  id integer primary key autoincrement, name text, url text, token text, org text,
  is_default integer default 0, created real, username text);
create table if not exists feedback(
  run_id integer, finding_id integer, verdict text, note text, username text, ts real,
  primary key(run_id, finding_id));
create table if not exists settings(key text primary key, value text);
create table if not exists notes(
  id integer primary key autoincrement, run_id integer, frame integer, name text, box text, msg text,
  username text, ts real);
create table if not exists edits(run_id integer, finding_id integer, msg text, username text, ts real,
  primary key(run_id, finding_id));
"""
RUN_EXTRA = {"connection_id": "integer", "job_name": "text", "task_name": "text", "project_name": "text",
             "assignee": "text", "job_stage": "text", "job_state": "text", "source": "text"}
DEFAULT_SETTINGS = {"pass_threshold": 0.97, "default_mode": "chinh_xac", "webhook_enabled": False,
                    "webhook_secret": "", "webhook_connection_id": None, "webhook_auto_push": False}


def conn():
    os.makedirs(DATA, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, conn() as c:
        c.executescript(SCHEMA)
        have = {r["name"] for r in c.execute("pragma table_info(runs)")}
        for col, typ in RUN_EXTRA.items():              # nang cap CSDL cu: them cot moi
            if col not in have:
                c.execute(f"alter table runs add column {col} {typ}")
        # lan review dang chay khi tat web -> danh dau loi (worker khong con)
        c.execute("update runs set status='loi', error='Web bị tắt khi đang chạy' where status in ('cho','dang_chay')")
        if not c.execute("select 1 from users where role='admin'").fetchone():
            pw = os.environ.get("WEB_QC_ADMIN_PASSWORD") or secrets.token_urlsafe(9)
            c.execute("insert or replace into users values(?,?,?,?)", ("admin", hash_pw(pw), "admin", time.time()))
            path = os.path.join(DATA, "MAT_KHAU_ADMIN.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"Tai khoan: admin\nMat khau: {pw}\n(Dang nhap xong vao Cai dat doi mat khau roi xoa file nay.)\n")
            print(f"Da tao tai khoan admin. Mat khau o: {path}", flush=True)


# ---------------------------------------------------------------- khoa may chu + ma hoa token
def secret_key():
    os.makedirs(DATA, exist_ok=True)
    p = os.path.join(DATA, "secret.key")
    if not os.path.exists(p):
        with open(p, "w") as f:
            f.write(secrets.token_hex(32))
    return open(p).read().strip()


def _stream(key, nonce, n):
    out, i = b"", 0
    while len(out) < n:
        out += hmac.new(key, nonce + i.to_bytes(4, "big"), hashlib.sha256).digest()
        i += 1
    return out[:n]


def enc(text):
    if not text:
        return ""
    key = hashlib.sha256(("token:" + secret_key()).encode()).digest()
    nonce = secrets.token_bytes(12)
    raw = text.encode()
    ct = bytes(a ^ b for a, b in zip(raw, _stream(key, nonce, len(raw))))
    return "v1:" + base64.b64encode(nonce + ct).decode()


def dec(blob):
    if not blob:
        return ""
    if not blob.startswith("v1:"):
        return blob                                  # du lieu cu chua ma hoa
    data = base64.b64decode(blob[3:])
    key = hashlib.sha256(("token:" + secret_key()).encode()).digest()
    nonce, ct = data[:12], data[12:]
    return bytes(a ^ b for a, b in zip(ct, _stream(key, nonce, len(ct)))).decode()


def mask(token):
    return ("••••" + token[-4:]) if token else ""


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


# ---------------------------------------------------------------- ket noi CVAT
def _conn_row(r, with_token=False):
    if r is None:
        return None
    d = dict(r)
    tok = dec(d.pop("token") or "")
    d["token_mask"] = mask(tok)
    d["has_token"] = bool(tok)
    d["is_default"] = bool(d["is_default"])
    if with_token:
        d["token"] = tok
    return d


def list_connections(with_token=False):
    with conn() as c:
        return [_conn_row(r, with_token) for r in c.execute("select * from connections order by is_default desc, name")]


def get_connection(cid, with_token=True):
    if not cid:
        return None
    with conn() as c:
        return _conn_row(c.execute("select * from connections where id=?", (cid,)).fetchone(), with_token)


def default_connection(with_token=True):
    with conn() as c:
        r = c.execute("select * from connections order by is_default desc, id limit 1").fetchone()
    return _conn_row(r, with_token)


def save_connection(cid, name, url, token, org, is_default, username):
    """token None hoac '' khi sua = giu token cu."""
    url = (url or "").strip().rstrip("/")
    if url.endswith("/api"):
        url = url[:-4]
    with _lock, conn() as c:
        if is_default:
            c.execute("update connections set is_default=0")
        if cid:
            old = c.execute("select * from connections where id=?", (cid,)).fetchone()
            if old is None:
                raise ValueError("Không có kết nối này.")
            c.execute("update connections set name=?, url=?, token=?, org=? where id=?",
                      (name, url, enc(token) if token else old["token"], org or "", cid))
            if is_default:
                c.execute("update connections set is_default=1 where id=?", (cid,))
        else:
            first = not c.execute("select 1 from connections").fetchone()
            cur = c.execute("insert into connections(name,url,token,org,is_default,created,username) values(?,?,?,?,?,?,?)",
                            (name, url, enc(token), org or "", int(bool(is_default) or first), time.time(), username))
            cid = cur.lastrowid
        if not c.execute("select 1 from connections where is_default=1").fetchone():
            c.execute("update connections set is_default=1 where id=(select min(id) from connections)")
    return cid


def del_connection(cid):
    with _lock, conn() as c:
        c.execute("delete from connections where id=?", (cid,))
        if not c.execute("select 1 from connections where is_default=1").fetchone():
            c.execute("update connections set is_default=1 where id=(select min(id) from connections)")


def import_env_connection(url, token, org="", name=".env trên máy chủ"):
    """Nhap ket noi tu file .env neu chua co ket noi nao trung URL + token."""
    if not (url and token):
        return None
    url = url.strip().rstrip("/")
    for c in list_connections(with_token=True):
        if c["url"] == url and c["token"] == token:
            return c["id"]
    return save_connection(None, name, url, token, org, False, "system")


# ---------------------------------------------------------------- cai dat chung
def get_settings():
    out = dict(DEFAULT_SETTINGS)
    with conn() as c:
        for r in c.execute("select * from settings"):
            out[r["key"]] = json.loads(r["value"])
    return out


def set_settings(**kw):
    with _lock, conn() as c:
        for k, v in kw.items():
            if k in DEFAULT_SETTINGS:
                c.execute("insert or replace into settings values(?,?)", (k, json.dumps(v)))


# ---------------------------------------------------------------- lan review
def _row(r):
    if r is None:
        return None
    d = dict(r)
    for k in ("params", "stats", "pushed"):
        d[k] = json.loads(d[k]) if d.get(k) else None
    return d


def new_run(job_id, task_id, username, params, guideline_id, connection_id=None, source="web"):
    with _lock, conn() as c:
        cur = c.execute("insert into runs(job_id,task_id,username,status,created,params,guideline_id,connection_id,source) "
                        "values(?,?,?,?,?,?,?,?,?)",
                        (job_id, task_id, username, "cho", time.time(), json.dumps(params), guideline_id, connection_id, source))
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


def list_runs(limit=300, job_id=None):
    with conn() as c:
        if job_id:
            rs = c.execute("select * from runs where job_id=? order by id desc limit ?", (job_id, limit))
        else:
            rs = c.execute("select * from runs order by id desc limit ?", (limit,))
        return [_row(r) for r in rs]


# ---------------------------------------------------------------- phan hoi "tool nham"
def set_feedback(run_id, finding_id, verdict, note, username):
    with _lock, conn() as c:
        if verdict:
            c.execute("insert or replace into feedback values(?,?,?,?,?,?)", (run_id, finding_id, verdict, note or "", username, time.time()))
        else:
            c.execute("delete from feedback where run_id=? and finding_id=?", (run_id, finding_id))


def get_feedback(run_id):
    with conn() as c:
        return {r["finding_id"]: dict(verdict=r["verdict"], note=r["note"], username=r["username"])
                for r in c.execute("select * from feedback where run_id=?", (run_id,))}


def feedback_counts():
    with conn() as c:
        return {r["run_id"]: r["n"] for r in c.execute("select run_id, count(*) n from feedback where verdict='tool_nham' group by run_id")}


# ---------------------------------------------------------------- ghi chu tay + sua loi nhan
def add_note(run_id, frame, name, box, msg, username):
    with _lock, conn() as c:
        cur = c.execute("insert into notes(run_id,frame,name,box,msg,username,ts) values(?,?,?,?,?,?,?)",
                        (run_id, frame, name, json.dumps([round(float(v), 1) for v in box]), msg, username, time.time()))
        return cur.lastrowid


def update_note(note_id, msg):
    with _lock, conn() as c:
        c.execute("update notes set msg=? where id=?", (msg, note_id))


def del_note(note_id):
    with _lock, conn() as c:
        c.execute("delete from notes where id=?", (note_id,))


def get_notes(run_id):
    with conn() as c:
        return [dict(id=r["id"], frame=r["frame"], name=r["name"], box=json.loads(r["box"]), msg=r["msg"], username=r["username"], ts=r["ts"])
                for r in c.execute("select * from notes where run_id=? order by id", (run_id,))]


def set_edit(run_id, finding_id, msg, username):
    with _lock, conn() as c:
        if msg:
            c.execute("insert or replace into edits values(?,?,?,?,?)", (run_id, finding_id, msg, username, time.time()))
        else:
            c.execute("delete from edits where run_id=? and finding_id=?", (run_id, finding_id))


def get_edits(run_id):
    with conn() as c:
        return {r["finding_id"]: r["msg"] for r in c.execute("select * from edits where run_id=?", (run_id,))}


def avg_sec_per_image(default=1.5):
    """Toc do trung binh tu 20 lan review gan nhat (de uoc luong thoi gian cho)."""
    with conn() as c:
        rs = [json.loads(r["stats"]) for r in c.execute("select stats from runs where status='xong' and stats is not null order by id desc limit 20")]
    sp = [s["giay"] / s["frames"] for s in rs if s.get("frames") and s.get("giay")]
    return sum(sp) / len(sp) if sp else default


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
                    has_rules=bool((r["rules"] or "").strip()), n_chars=len(r["text"] or ""), rules=r["rules"] or "")
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
