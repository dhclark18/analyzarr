import os
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from flask import (
    Flask, render_template, abort, flash,
    redirect, url_for, request, jsonify
)
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
        
# ─── Utilities ────────────────────────────────────────────────────────────────
# define a regex-based test
def regex_match(value, pattern):
    """Return True if `pattern` (a string regex) matches `value`."""
    if value is None:
        return False
    return re.search(pattern, value) is not None

# register it under the name "match"
app.jinja_env.tests['match'] = regex_match

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

    # 2) Pull episodes + tags from Postgres (now selecting e.key too)
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT
          e.key,
          e.code,
          e.expected_title,
          e.actual_title,
          e.confidence,
          COALESCE(string_agg(t.name, ','), '') AS tags
        FROM episodes e
        LEFT JOIN episode_tags et ON e.key = et.episode_key
        LEFT JOIN tags t          ON et.tag_id = t.id
        WHERE e.series_title = %s
        GROUP BY e.key, e.code, e.expected_title, e.actual_title, e.confidence
        ORDER BY e.code;
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

    # 4) Enrich each DB row with the correct Sonarr ID AND preserve “key”
    enriched_rows = []
    for row in db_rows:
        key            = row["key"]
        code           = row["code"]           # e.g. "S14E11"
        expected_title = row["expected_title"]
        actual_title   = row["actual_title"]
        confidence     = row["confidence"]
        tags           = row["tags"]

        m = re.match(r"(?i)^S(\d{2})E(\d{2})$", code)
        if not m:
            sonarr_id = None
        else:
            season = int(m.group(1))
            epnum  = int(m.group(2))
            sonarr_id = by_season_ep.get((season, epnum))

        enriched_rows.append({
            "key":            key,
            "code":           code,
            "expected_title": expected_title,
            "actual_title":   actual_title,
            "confidence":     confidence,
            "tags":           tags,
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

@app.route("/override", methods=["POST"])
def override_episode():
    key = request.form.get("key")
    if not key:
        flash("No key provided for override", "danger")
        return redirect(request.referrer or url_for("index"))

    conn = get_db()
    cur = conn.cursor()

    # 1) Update confidence to 1.0 in episodes table
    cur.execute(
        "UPDATE episodes SET confidence = %s WHERE key = %s",
        (1.0, key)
    )

    # 2) Remove any 'problematic-episode' tag for this episode
    #    (First, look up the tag_id for 'problematic-episode')
    cur.execute("SELECT id FROM tags WHERE name = %s", ("problematic-episode",))
    row = cur.fetchone()
    if row:
        prob_tag_id = row["id"]
        cur.execute(
            "DELETE FROM episode_tags WHERE episode_key = %s AND tag_id = %s",
            (key, prob_tag_id)
        )

    # 3) Ensure the 'matched' tag exists (insert if missing)
    cur.execute("SELECT id FROM tags WHERE name = %s", ("matched",))
    row = cur.fetchone()
    if row:
        matched_tag_id = row["id"]
    else:
        cur.execute(
            "INSERT INTO tags (name) VALUES (%s) RETURNING id",
            ("matched",)
        )
        matched_tag_id = cur.fetchone()["id"]
    #    Add 'matched' to episode_tags (ignore conflict)
    cur.execute(
        """
        INSERT INTO episode_tags (episode_key, tag_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (key, matched_tag_id)
    )

    # 4) Ensure the 'override' tag exists (insert if missing)
    cur.execute("SELECT id FROM tags WHERE name = %s", ("override",))
    row = cur.fetchone()
    if row:
        override_tag_id = row["id"]
    else:
        cur.execute(
            "INSERT INTO tags (name) VALUES (%s) RETURNING id",
            ("override",)
        )
        override_tag_id = cur.fetchone()["id"]
    #    Add 'override' to episode_tags (ignore conflict)
    cur.execute(
        """
        INSERT INTO episode_tags (episode_key, tag_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (key, override_tag_id)
    )

    conn.commit()
    cur.close()
    conn.close()

    flash(f"Episode {key} overridden: confidence set to 1.0, tags updated.", "success")
    return redirect(request.referrer or url_for("index"))

@app.route("/series/<int:series_id>/episode/<key>")
def episode_details(series_id, key):
    # 1) Find the series title
    all_series = fetch_series_from_sonarr()
    info = next((s for s in all_series if s["id"] == series_id), None)
    if not info:
        abort(404, description="Series not found in Sonarr")
    series_title = info["title"]

    # 2) Fetch the episode row, including all new columns
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT
          e.expected_title,
          e.actual_title,
          e.confidence AS stored_conf,
          e.norm_expected,
          e.norm_extracted,
          e.substring_override,
          e.missing_title,
          COALESCE(string_agg(t.name, ','), '') AS tags
        FROM episodes e
        LEFT JOIN episode_tags et ON e.key = et.episode_key
        LEFT JOIN tags t        ON et.tag_id = t.id
        WHERE e.key = %s AND e.series_title = %s
        GROUP BY
          e.expected_title,
          e.actual_title,
          e.confidence,
          e.norm_expected,
          e.norm_extracted,
          e.substring_override,
          e.missing_title;
    """, (key, series_title))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        abort(404, description="Episode not found in database")

    # 3) Unpack everything
    expected_title      = row["expected_title"]
    actual_title        = row["actual_title"]
    stored_conf         = float(row["stored_conf"])
    norm_expected       = row["norm_expected"]
    norm_extracted      = row["norm_extracted"]
    substring_override  = row["substring_override"]
    missing_title       = row["missing_title"]
    tags_csv            = row["tags"]
    tag_list            = tags_csv.split(',') if tags_csv else []

    # 4) Pass directly into the template
    return render_template(
        "episode_details.html",
        series_id=series_id,
        series_title=series_title,
        key=key,
        expected_title=expected_title,
        actual_title=actual_title,
        stored_conf=stored_conf,
        norm_expected=norm_expected,
        norm_extracted=norm_extracted,
        substring_override=substring_override,
        missing_title=missing_title,
        base_conf=0.8,   
        exp=1,            
        tag_list=tag_list
    )
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
