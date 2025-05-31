import os
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from flask import Flask, render_template, abort, flash, redirect, url_for, request

# ─── Import your standalone cleanup logic and SonarrClient ────────────────────
#    (Assumes you have a cleanup.py next to this file that defines cleanup_deleted,
#     SonarrClient, and re-exports SONARR_URL/SONARR_API_KEY/API_TIMEOUT.)
from cleanup import cleanup_deleted, SonarrClient, SONARR_URL, SONARR_API_KEY, API_TIMEOUT

app = Flask(__name__)
# Secret key required for flash() to work
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change‐this‐to‐something‐secret")

# ─── Configuration ────────────────────────────────────────────────────────────
DATABASE_URL    = os.getenv("DATABASE_URL")
SONARR_URL      = os.getenv("SONARR_URL", "http://localhost:8989").rstrip("/")
SONARR_API_KEY  = os.getenv("SONARR_API_KEY")
if not SONARR_API_KEY:
    raise RuntimeError("Set SONARR_API_KEY in your environment")

SONARR_HEADERS  = {"X-Api-Key": SONARR_API_KEY}
SONARR_SESSION  = requests.Session()
SONARR_SESSION.headers.update(SONARR_HEADERS)

# ─── Instantiate a single SonarrClient for cleanup ───────────────────────────
#    Reuse this for every “Purge” click.
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
    # Build a simple list: [{ "title": "...", "id": 123 }, ...]
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

    # Build a mapping: { series_title: mismatch_count, ... }
    counts = {r["series_title"]: r["mismatch_count"] for r in rows}

    # 3) Merge mismatch counts into the series list
    for s in series:
        s["mismatch_count"] = counts.get(s["title"], 0)

    # 4) Pass series (with mismatch_count) into the template
    return render_template("index.html", series=series)


@app.route("/series/<int:series_id>")
def view_series(series_id):
    # — fetch series info from Sonarr (unchanged) —
    all_series = fetch_series_from_sonarr()
    info = next((s for s in all_series if s["id"] == series_id), None)
    if not info:
        abort(404, description="Series not found in Sonarr")

    # — pull episodes + tags from Postgres (same SQL as before) —
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
    rows = cur.fetchall()
    cur.close()
    conn.close()

    # — group by season number extracted from code "SxxEyy" —
    seasons = {}
    for ep in rows:
        season_num = int(ep["code"][1:3])
        seasons.setdefault(season_num, []).append(ep)

    return render_template(
        "episodes.html",
        series_title=info["title"],
        seasons=seasons
    )


@app.route("/cleanup", methods=["POST"])
def cleanup_route():
    """
    Trigger a one-off cleanup: deletes any episodes (and their tags/mismatch rows)
    that Sonarr no longer returns. Then redirect back to the referring page.
    """
    try:
        cleanup_deleted(sonarr_client)
        flash("🗑️ Cleanup complete: database synced with Sonarr.", "success")
    except Exception as e:
        app.logger.exception("Error during cleanup")
        flash(f"Cleanup failed: {e}", "danger")

    # Redirect back to the page the user came from (or to index() if unknown)
    ref = request.referrer or url_for("index")
    return redirect(ref)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
