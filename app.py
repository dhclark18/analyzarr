import os
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from flask import Flask, render_template, abort, flash, redirect, url_for, request
from analyzer import SonarrClient, grab_best_nzb, delete_episode_file, compute_confidence
import re
import logging

# ─── Import your standalone cleanup logic and ────────────────────
#    (Assumes you have a cleanup.py next to this file that defines cleanup_deleted,
from cleanup import cleanup_deleted

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
API_TIMEOUT    = int(os.getenv("API_TIMEOUT", "10"))

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
    # — existing Sonarr lookup to get series “title” —
    all_series = fetch_series_from_sonarr()
    info = next((s for s in all_series if s["id"] == series_id), None)
    if not info:
        abort(404, description="Series not found in Sonarr")

    # 1) Pull episodes + tags from your Postgres (as before)
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

    # 2) For each row, do a quick Sonarr call to get the episode’s internal ID
    #    We’ll build a new list of dicts, adding “sonarr_id”
    enriched_rows = []
    for ep in rows:
        # ep["code"] is like "S14E11"
        import re
        m = re.match(r"(?i)^S(\d{2})E(\d{2})$", ep["code"])
        if not m:
            # fallback: skip Sonarr lookup if code malformed
            sonarr_id = None
        else:
            season = int(m.group(1))
            epnum  = int(m.group(2))
            # call Sonarr: GET /episode?seriesId=…&seasonNumber=…&episodeNumber=…
            endpoint = f"episode?seriesId={series_id}&seasonNumber={season}&episodeNumber={epnum}"
            try:
                result = sonarr_client.get(endpoint) or []
                sonarr_id = result[0].get("id") if (isinstance(result, list) and result) else None
            except Exception:
                sonarr_id = None

        enriched_rows.append({
            "code":            ep["code"],
            "expected_title":  ep["expected_title"],
            "actual_title":    ep["actual_title"],
            "confidence":      ep["confidence"],
            "tags":            ep["tags"],
            "sonarr_id":       sonarr_id
        })

    # 3) Group by season for the template
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

    # ─── Pass series_id into the template ───────────────────────────────────
    return render_template(
        "episodes.html",
        series_id=series_id,            # ← NEW
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

@app.route("/series/<int:series_id>/episode/<code>/auto-fix", methods=["POST"])
def auto_fix(series_id: int, code: str):
    """
    1) Parse season & episode from code (e.g. “S12E13”).
    2) Call SonarrClient.get("episode?seriesId=…&seasonNumber=…&episodeNumber=…")
       to retrieve the internal episodeId.
    3) Invoke grab_best_nzb(sonarr_client, series_id, episode_id).
    4) Flash a result and redirect back to view_series.
    """
    import re
    import logging
    from flask import flash, redirect, url_for

    # 1) Parse SxxEyy from `code`
    m = re.match(r"(?i)^S(\d{2})E(\d{2})$", code)
    if not m:
        flash("❌ Invalid episode code.", "danger")
        return redirect(url_for("view_series", series_id=series_id))

    season = int(m.group(1))
    epnum  = int(m.group(2))

    # 2) Look up Sonarr’s internal episodeId by embedding query parameters
    try:
        endpoint = (
            f"episode?seriesId={series_id}"
            f"&seasonNumber={season}"
            f"&episodeNumber={epnum}"
        )
        r = sonarr_client.get(endpoint) or []
        if not isinstance(r, list) or not r:
            flash(f"❌ Episode {code} not found in Sonarr.", "danger")
            return redirect(url_for("view_series", series_id=series_id))

        episode_id = r[0].get("id")
        if episode_id is None:
            flash(f"❌ Could not extract episode ID for {code}.", "danger")
            return redirect(url_for("view_series", series_id=series_id))

    except Exception as ex:
        logging.exception("Error looking up episodeId in Sonarr")
        flash("❌ Could not retrieve episode ID from Sonarr.", "danger")
        return redirect(url_for("view_series", series_id=series_id))

    # 3) Call your existing grab_best_nzb helper
    try:
        grab_best_nzb(sonarr_client, series_id, episode_id, wait=5)
        flash(f"🔧 Auto-Fix triggered for {code}.", "success")
    except Exception as ex:
        logging.exception("Auto-Fix failed")
        flash(f"❌ Auto-Fix failed: {ex}", "danger")

    # 4) Redirect back to the series page
    return redirect(url_for("view_series", series_id=series_id))
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
