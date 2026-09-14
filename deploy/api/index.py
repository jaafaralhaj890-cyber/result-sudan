# -*- coding: utf-8 -*-
"""
Vercel Serverless Function - Sudan Exam Results API
"""

from http.server import BaseHTTPRequestHandler
import gzip
import json
import os
import re
import sqlite3
import urllib.parse

# في بيئة Vercel، مجلد /tmp هو المكان الوحيد القابل للكتابة
DB_TMP_PATH = "/tmp/results.db"
GZ_PATH = os.path.join(os.path.dirname(__file__), "..", "results.db.gz")


def ensure_db():
    if not os.path.exists(DB_TMP_PATH) or os.path.getsize(DB_TMP_PATH) == 0:
        if os.path.exists(GZ_PATH):
            with gzip.open(GZ_PATH, "rb") as f_in:
                with open(DB_TMP_PATH, "wb") as f_out:
                    f_out.write(f_in.read())


def normalize_arabic(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[\u064B-\u065F\u0640]", "", text)
    text = re.sub(r"[إأآا]", "ا", text)
    text = re.sub(r"[ة]", "ه", text)
    text = re.sub(r"[ى]", "ي", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\bعبد\s+", "عبد", text)
    text = re.sub(r"\b(سيف|نور|عز|تاج|شمس|ضياء|محي|نجم)\s+الدين\b", r"\1الدين", text)
    return re.sub(r"\s+", " ", text).strip()


def search_seat(seat: int):
    ensure_db()
    with sqlite3.connect(DB_TMP_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT seat, name, pct, result, rank_national, percentile_all, percentile_pass FROM students WHERE seat = ?",
            (seat,),
        )
        row = cur.fetchone()
        if row:
            return {
                "seat": row["seat"],
                "name": row["name"],
                "pct": row["pct"],
                "result": row["result"],
                "rank": row["rank_national"],
                "percentile_all": row["percentile_all"],
                "percentile_pass": row["percentile_pass"],
            }
    return None


def search_name(query: str, limit: int = 50):
    ensure_db()
    norm = normalize_arabic(query)
    if not norm:
        return []
    tokens = [t for t in norm.split() if t]
    if not tokens:
        return []

    with sqlite3.connect(DB_TMP_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        fts_match = " AND ".join(f'"{t}"*' for t in tokens)
        try:
            cur.execute(
                f"""
            SELECT s.seat, s.name, s.pct, s.result, s.rank_national, s.percentile_all, s.percentile_pass
            FROM students s
            JOIN students_fts f ON s.seat = f.rowid
            WHERE students_fts MATCH ?
            ORDER BY s.pct DESC
            LIMIT ?
            """,
                (fts_match, limit),
            )
            rows = cur.fetchall()
            if rows:
                return [
                    {
                        "seat": r["seat"],
                        "name": r["name"],
                        "pct": r["pct"],
                        "result": r["result"],
                        "rank": r["rank_national"],
                        "percentile_all": r["percentile_all"],
                        "percentile_pass": r["percentile_pass"],
                    }
                    for r in rows
                ]
        except Exception:
            pass

        like_clauses = " AND ".join(["name_normalized LIKE ?"] * len(tokens))
        params = [f"%{t}%" for t in tokens] + [limit]
        cur.execute(
            f"""
        SELECT seat, name, pct, result, rank_national, percentile_all, percentile_pass
        FROM students
        WHERE {like_clauses}
        ORDER BY pct DESC
        LIMIT ?
        """,
            params,
        )
        rows = cur.fetchall()
        return [
            {
                "seat": r["seat"],
                "name": r["name"],
                "pct": r["pct"],
                "result": r["result"],
                "rank": r["rank_national"],
                "percentile_all": r["percentile_all"],
                "percentile_pass": r["percentile_pass"],
            }
            for r in rows
        ]


def get_stats():
    ensure_db()
    with sqlite3.connect(DB_TMP_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), AVG(pct) FROM students")
        total, avg_pct = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM students WHERE result = 'نجاح' OR pct >= 50.0")
        passed = cur.fetchone()[0]
        cur.execute("SELECT seat, name, pct FROM students ORDER BY pct DESC LIMIT 1")
        top = cur.fetchone()
        return {
            "total_students": total,
            "passed_students": passed,
            "passing_rate": round((passed / total * 100), 2) if total else 0,
            "avg_percentage": round(avg_pct, 2) if avg_pct else 0,
            "top_student": {
                "seat": top[0],
                "name": top[1],
                "pct": top[2],
            }
            if top
            else None,
        }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path.endswith("/search") or "/api/search" in path:
            q = params.get("q", [""])[0].strip()
            limit = min(int(params.get("limit", [50])[0]), 200)
            if not q:
                self.send_json({"error": "يرجى إدخال اسم أو رقم جلوس", "results": []}, 400)
                return
            if q.isdigit():
                student = search_seat(int(q))
                results = [student] if student else []
                stype = "seat"
            else:
                results = search_name(q, limit=limit)
                stype = "name"
            self.send_json({"query": q, "type": stype, "count": len(results), "results": results})
        elif path.endswith("/stats") or "/api/stats" in path:
            self.send_json(get_stats())
        else:
            self.send_json({"status": "ok", "service": "Sudan Exam Results API"})

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass
