import os
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from flask import Flask, render_template, abort, flash, redirect, url_for, request, jsonify
from analyzer import SonarrClient, grab_best_nzb, delete_episode_file, compute_confidence
import re
import logging
import threading

# ─── Import your standalone cleanup logic ─────────────────────────────────────
from cleanup import cleanup_deleted

app = Flask(__name__)
# Secret key required for flash() to work
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-to-something-secret")

# ─── Configuration ────────────────────────────────────────────────────────────
DATABASE_URL    = os.getenv("DATABASE_URL")
SONARR_URL      = os.getenv("SONARR_URL", "http://localhost:8989").rstrip("/")
SONARR_API_KEY  = os.getenv("SONARR_API_KEY")
if not SONARR_API_KEY:
    raise RuntimeError("Set SONARR_API_KEY in your environment")

SONARR_HEADERS  = {"X-Api-Key": SONARR_API_KEY}
SONARR_SESSION  = requests.Session()
SONARR_SESSION.headers.update(SONARR_HEADERS)
API_TIMEOUT     = int(os.getenv("API_TIMEOUT", "10"))

# ─── Instantiate a single SonarrClient for cleanup ────────────────────────────
sonarr_client = SonarrClient(SONARR_URL, SONARR_API_KEY, timeout=API_TIMEOUT)

# ─── Database helper ──────────────────────────────────────────────────────────
def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    
# ─── Sonarr helper ────────────────────────────────────────────────────────────
def fetch_series_from_sonarr():
    """Return list of series dicts from Sonarr API, or abort(500) on error."""
    try:
        resp = SONARR_SESSION.get(f"{SONARR_URL}/api/v3/series")
        resp.raise_for_status()
        return resp.json()  # list of series objects
    except Exception as e:
        app.logger.error("❌ Sonarr API error fetching series: %s", e)
        abort(500, description="Failed to fetch series from Sonarr")

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    # 1) Pull list of series from Sonarr
    series_list = fetch_series_from_sonarr()
    series = [{"title": s["title"], "id": s["id"]} for s in series_list]
    series.sort(key=lambda x: x["title"].lower())

    # 2) Query Postgres for per-series “problematic-episode” counts
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT
          e.series_title,
          COUNT(*) AS mismatch_count
        FROM episodes e
        JOIN episode_tags et ON e.key = et.episode_key
        JOIN tags t ON et.tag_id = t.id
        WHERE t.name = 'problematic-episode'
        GROUP BY e.series_title;
    """)
    rows = cur.fetchall()  # rows like [ {"series_title": "The Office", "mismatch_count": 5}, ... ]
    cur.close()
    conn.close()

    counts = {r["series_title"]: r["mismatch_count"] for r in rows}
    for s in series:
        s["mismatch_count"] = counts.get(s["title"], 0)

    return render_template("index.html", series=series)

@app.route("/series/<int:series_id>")
def view_series(series_id):
    # 1) Find the series title (as before)
    all_series = fetch_series_from_sonarr()
    info = next((s for s in all_series if s["id"] == series_id), None)
    if not info:
        abort(404, description="Series not found in Sonarr")

    # 2) Pull episodes + tags from Postgres (same as before)
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT 
          e.code,
          e.expected_title,
          e.actual_title,
          e.confidence,
          COALESCE(string_agg(t.name, ','), '') AS tags
        FROM episodes e
        LEFT JOIN episode_tags et ON e.key = et.episode_key
        LEFT JOIN tags t          ON et.tag_id = t.id
        WHERE e.series_title = %s
        GROUP BY e.key
        ORDER BY e.code
    """, (info["title"],))
    db_rows = cur.fetchall()
    cur.close()
    conn.close()

    # 3) Fetch *all* Sonarr episodes for this series in one shot:
    #    GET /api/v3/episode?seriesId=<series_id>
    try:
        sonarr_eps = sonarr_client.get(f"episode?seriesId={series_id}") or []
    except Exception:
        sonarr_eps = []
    #    Build a lookup: (season, episode) → episodeId
    by_season_ep = {
        (ep["seasonNumber"], ep["episodeNumber"]): ep["id"]
        for ep in sonarr_eps
    }

    # 4) Enrich each DB row with the correct Sonarr ID
    enriched_rows = []
    for ep in db_rows:
        code = ep["code"]  # e.g. "S14E11"
        m = re.match(r"(?i)^S(\d{2})E(\d{2})$", code)
        if not m:
            sonarr_id = None
        else:
            season = int(m.group(1))
            epnum  = int(m.group(2))
            sonarr_id = by_season_ep.get((season, epnum))

        enriched_rows.append({
            "code":           code,
            "expected_title": ep["expected_title"],
            "actual_title":   ep["actual_title"],
            "confidence":     ep["confidence"],
            "tags":           ep["tags"],
            "sonarr_id":      sonarr_id
        })

    # 5) Group by season for rendering
    seasons = {}
    for ep in enriched_rows:
        season_num = int(ep["code"][1:3])
        seasons.setdefault(season_num, []).append(ep)

    return render_template(
        "episodes.html",
        series_id=series_id,
        series_title=info["title"],
        seasons=seasons
    )

@app.route("/cleanup", methods=["POST"])
def cleanup_route():
    """
    Instead of doing a blocking form‐submit → redirect, we now:
      • Run cleanup_deleted(...) synchronously.
      • Return JSON { status, message } when done.
    """
    try:
        cleanup_deleted(sonarr_client)
    except Exception as e:
        app.logger.exception("Error during cleanup")
        return jsonify({
            "status": "error",
            "message": f"Cleanup failed: {e}"
        }), 500

    return jsonify({
        "status":  "success",
        "message": "Cleanup complete: database synced with Sonarr."
    }), 200
    
@app.route("/series/<int:series_id>/episode/auto-fix", methods=["POST"])
def auto_fix(series_id: int):
    """
    1) Read 'episode_id' from JSON payload.
    2) Verify it belongs to the series.
    3) Call grab_best_nzb(...) synchronously.
    4) Return JSON when done.
    """
    from flask import jsonify

    # 1) Pull episode_id from JSON body (not form)
    data = request.get_json(silent=True) or {}
    episode_id = data.get("episode_id")
    logging.debug(f"▶ auto_fix JSON payload: episode_id={episode_id!r}")

    try:
        episode_id = int(episode_id)
    except (TypeError, ValueError):
        return jsonify({"status":"error", "message":"Invalid episode_id"}), 400

    # 2) Verify episode belongs to this series
    try:
        ep_info = sonarr_client.get(f"episode/{episode_id}") or {}
        if ep_info.get("seriesId") != series_id:
            return jsonify({
                "status":  "error",
                "message": "Episode ID does not match this series"
            }), 400
    except Exception:
        logging.exception("Error validating episode ID in Sonarr")
        return jsonify({"status":"error", "message":"Sonarr lookup failed"}), 500

    # 3) Run grab_best_nzb(...) *synchronously* (blocking HTTP until it finishes)
    try:
        grab_best_nzb(sonarr_client, series_id, episode_id, wait=5)
    except Exception as ex:
        logging.exception("grab_best_nzb failed")
        return jsonify({
            "status":  "error",
            "message": f"Auto-Fix failed: {ex}"
        }), 500

    # 4) Success
    return jsonify({"status":"success", "message":"Auto-Fix complete"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
