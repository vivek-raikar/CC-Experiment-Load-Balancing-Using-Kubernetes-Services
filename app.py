import os
import socket
import time
import zlib

import pymysql
from flask import Flask, jsonify, redirect, render_template_string, request

app = Flask(__name__)

POD_NAME = os.getenv("POD_NAME", socket.gethostname())
NODE_NAME = os.getenv("NODE_NAME", "unknown")
POD_IP = os.getenv("POD_IP", "unknown")


def get_db():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "mysql"),
        user=os.getenv("DB_USER", "labuser"),
        password=os.getenv("DB_PASSWORD", "labpass"),
        database=os.getenv("DB_NAME", "labdb"),
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )


def init_db():
    """Create tables; retry because MySQL may still be starting."""
    for attempt in range(30):
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS notes ("
                    "id INT AUTO_INCREMENT PRIMARY KEY,"
                    "text VARCHAR(200) NOT NULL,"
                    "added_by_pod VARCHAR(100) NOT NULL,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS request_log ("
                    "id INT AUTO_INCREMENT PRIMARY KEY,"
                    "pod VARCHAR(100) NOT NULL,"
                    "node VARCHAR(100) NOT NULL,"
                    "path VARCHAR(100) NOT NULL,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
            conn.close()
            print("Database ready", flush=True)
            return
        except Exception as exc:
            print(f"DB not ready (attempt {attempt + 1}): {exc}", flush=True)
            time.sleep(2)
    raise RuntimeError("Could not connect to the database")


init_db()


@app.before_request
def log_request():
    # Only count the demo endpoints, not health checks or stats pages
    if request.path in ("/", "/api/whoami"):
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO request_log (pod, node, path) VALUES (%s, %s, %s)",
                    (POD_NAME, NODE_NAME, request.path),
                )
            conn.close()
        except Exception as exc:
            print(f"log error: {exc}", flush=True)


def read_stats():
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pod, node, COUNT(*) AS requests FROM request_log "
            "GROUP BY pod, node ORDER BY pod"
        )
        rows = cur.fetchall()
    conn.close()
    return rows


PAGE = """
<!doctype html>
<html><head><meta charset="utf-8"><title>LB Demo</title>
<style>
 body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f4f4f6;color:#222}
 header{background:hsl({{hue}},65%,38%);color:#fff;padding:24px 32px}
 header h1{margin:0 0 6px;font-size:26px} header p{margin:2px 0;font-size:15px}
 main{max-width:860px;margin:24px auto;padding:0 16px}
 .card{background:#fff;border-radius:10px;padding:18px 22px;margin-bottom:18px;box-shadow:0 1px 4px #0002}
 table{border-collapse:collapse;width:100%} td,th{padding:6px 10px;border-bottom:1px solid #eee;text-align:left}
 input[type=text]{padding:8px;width:60%} button{padding:8px 16px}
</style></head><body>
<header>
 <h1>Load Balancing Demo</h1>
 <p>Served by pod: <b>{{pod}}</b></p>
 <p>Running on node: <b>{{node}}</b> &nbsp;|&nbsp; Pod IP: <b>{{ip}}</b></p>
</header>
<main>
 <div class="card"><h3>Notes (stored in shared MySQL)</h3>
  <form method="post" action="/notes">
   <input type="text" name="text" placeholder="Write a note" required maxlength="200">
   <button type="submit">Add</button></form>
  <table><tr><th>#</th><th>Note</th><th>Added by pod</th></tr>
  {% for n in notes %}<tr><td>{{n.id}}</td><td>{{n.text}}</td><td>{{n.added_by_pod}}</td></tr>{% endfor %}
  </table></div>
 <div class="card"><h3>Requests handled per pod (from database)</h3>
  <table><tr><th>Pod</th><th>Node</th><th>Requests</th></tr>
  {% for s in stats %}<tr><td>{{s.pod}}</td><td>{{s.node}}</td><td>{{s.requests}}</td></tr>{% endfor %}
  </table></div>
</main></body></html>
"""


@app.route("/")
def index():
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT id, text, added_by_pod FROM notes ORDER BY id DESC LIMIT 10")
        notes = cur.fetchall()
    conn.close()
    hue = zlib.crc32(POD_NAME.encode()) % 360  # each pod gets its own colour
    return render_template_string(
        PAGE, pod=POD_NAME, node=NODE_NAME, ip=POD_IP, notes=notes,
        stats=read_stats(), hue=hue,
    )


@app.route("/notes", methods=["POST"])
def add_note():
    text = request.form.get("text", "").strip()[:200]
    if text:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notes (text, added_by_pod) VALUES (%s, %s)",
                (text, POD_NAME),
            )
        conn.close()
    return redirect("/")


@app.route("/api/whoami")
def whoami():
    return jsonify(pod=POD_NAME, node=NODE_NAME, ip=POD_IP)


@app.route("/api/stats")
def stats():
    return jsonify(read_stats())


@app.route("/api/reset", methods=["POST"])
def reset():
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE request_log")
    conn.close()
    return jsonify(status="request_log cleared")


@app.route("/health")
def health():  # liveness: is the app process alive?
    return "ok", 200


@app.route("/ready")
def ready():  # readiness: can this pod reach the database?
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        return "ready", 200
    except Exception:
        return "db unavailable", 503
