#!/usr/bin/env python3
# api.py

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, abort
from analyzer import grab_best_nzb, SonarrClient
from jobs import start_replace_job, get_job, jobs, jobs_lock

# ─── create the Flask app first ───────────────────────────────────────────
app = Flask(__name__)

# ─── initialize a single Sonarr client ──────────────────────────────────
sonarr = SonarrClient(
    base_url=os.getenv("SONARR_URL"),
    api_key=os.getenv("SONARR_API_KEY"),
    timeout=10
)
# ─── Main functions and routes ──────────────────────────────────
def compute_stats():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT
          COUNT(*)                            AS "totalEpisodes",
          COUNT(DISTINCT series_id)           AS "totalShows",
          COUNT(*) FILTER (WHERE substring_override) 
                                              AS "totalOverrides",
          COUNT(*) FILTER (WHERE missing_title) 
                                              AS "totalMissingTitles",
          COUNT(*) FILTER (
            WHERE confidence >= 0.5
              AND NOT substring_override
              AND NOT missing_title
          )                                   AS "totalMatches",
          (SELECT COUNT(*)
             FROM episodes e
             JOIN episode_tags et
               ON e.key = et.episode_key
             JOIN tags t
               ON et.tag_id = t.id
              AND t.name = 'problematic-episode'
          )                                   AS "totalMismatches",
          ROUND(AVG(confidence)::numeric, 2)  AS "avgConfidence"
        FROM episodes;
    """)
    stats = cur.fetchone()
    cur.close()
    conn.close()
    return stats
    
@app.route('/api/stats')
def stats():
    return jsonify(compute_stats())  
    
@app.route('/api/episodes/replace', methods=['POST']) #still needed?????
def replace_episode():
    """
    Expects JSON { key: <string> } where key is your episodes.key.
    Looks up series_id & episode_id in the DB, then calls grab_best_nzb.
    After replacement, triggers analyzer.py for that series (and season if known).
    """
    data = request.get_json() or {}
    key = data.get("key")
    if not key:
        return jsonify({ "error": "key required" }), 400

    # pull the IDs out of your episodes table
    conn = get_conn()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
      SELECT series_id, episode_id, code
        FROM episodes
       WHERE key = %s
    """, (key,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row or row.get("series_id") is None or row.get("episode_id") is None:
        return jsonify({ "error": "no series/episode IDs for key" }), 404

    try:
        grab_best_nzb(sonarr, row["series_id"], row["episode_id"])
    except Exception as e:
        return jsonify({ "error": str(e) }), 500

    # ─── Optional: parse season number from code (e.g. S02E03) ────────────────
    import re, subprocess
    season_match = re.match(r"S(\d{2})E\d{2}", row["code"] or "")
    season_num = int(season_match.group(1)) if season_match else None

    # ─── Trigger analyzer in the background for just this show/season ────────
    cmd = ["python3", "/app/analyzer.py", "--series-id", str(row["series_id"])]
    if season_num:
        cmd += ["--season", str(season_num)]

    subprocess.Popen(cmd)

    return jsonify({ "status": "replace triggered", "series_id": row["series_id"], "season": season_num }), 202
def compute_mismatch_counts():
    """
    Returns a list of { seriesTitle: str, count: int }
    by counting episodes tagged specifically with 'problematic-episode'.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
          e.series_title   AS "seriesTitle",
          COUNT(DISTINCT e.key) AS count
        FROM episodes e
        JOIN episode_tags et
          ON e.key = et.episode_key
        JOIN tags t
          ON et.tag_id = t.id
         AND t.name = %s
        GROUP BY e.series_title;
        """,
        ('problematic-episode',)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {"seriesTitle": r["seriesTitle"], "count": r["count"]}
        for r in rows
    ]

@app.route('/api/mismatches')
def mismatches():
    return jsonify(compute_mismatch_counts())

@app.route('/api/series/<series_title>/episodes')
def series_episodes(series_title):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT
          -- boolean: true if *no* problematic-episode tag
          NOT EXISTS (
            SELECT 1 FROM episode_tags et
            JOIN tags t ON et.tag_id = t.id
            WHERE et.episode_key = e.key
              AND t.name = 'problematic-episode'
          )             AS matches,
          e.code       AS code,
          CAST(SUBSTRING(e.code FROM '^S([0-9]{2})') AS INT) AS season,
          e.expected_title AS "expectedTitle",
          e.actual_title   AS "actualTitle",
          e.confidence AS confidence,
          e.series_id AS seriesId,
          e.episode_id AS episodeId,
          e.key        AS key
        FROM episodes e
        WHERE e.series_title = %s
        ORDER BY e.key;
    """, (series_title,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(rows)

@app.route('/api/episode/<path:key>')
def get_episode(key):
    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("""
        SELECT
          e.key,
          e.code,
          e.expected_title    AS "expectedTitle",
          e.norm_expected     AS "norm_expected",
          e.actual_title      AS "actualTitle",
          e.norm_extracted    AS "norm_extracted",
          e.norm_scene        AS "norm_scene",
          e.confidence,
          e.substring_override,
          e.missing_title,
          e.release_group,
          e.media_info,
          COALESCE(array_remove(array_agg(t.name), NULL), '{}') AS tags
        FROM episodes e
        LEFT JOIN episode_tags et ON e.key = et.episode_key
        LEFT JOIN tags t           ON et.tag_id = t.id
        WHERE e.key = %(key)s
        GROUP BY
          e.key, e.code,
          e.expected_title,
          e.norm_expected,
          e.actual_title,
          e.norm_extracted,
          e.norm_scene,
          e.confidence,
          e.substring_override,
          e.missing_title,
          e.release_group,
          e.media_info
    """, {'key': key})

    row = cur.fetchone()
    conn.close()

    if not row:
        abort(404)

    # row is a psycopg2.extras.DictRow (or similar), so dict(row) yields your JSON
    ep = dict(row)
    return jsonify(ep)

@app.route('/api/episode/<path:key>/tags', methods=['POST'])
def add_tag_to_episode(key):
    data = request.get_json() or {}
    tag = data.get('tag', '').strip()
    if not tag:
        abort(400, description="Missing 'tag' in request body")

    conn = get_conn()
    cur  = conn.cursor()

    # 1) Ensure the tag exists in the tags table
    cur.execute(
        "INSERT INTO tags(name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
        (tag,)
    )

    # 2) Get its ID
    cur.execute(
        "SELECT id FROM tags WHERE name = %s",
        (tag,)
    )
    tag_id = cur.fetchone()['id']

    # 3) Link it to the episode (no-op if already exists)
    cur.execute(
        "INSERT INTO episode_tags(episode_key, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (key, tag_id)
    )

    conn.commit()

    # 4) Return the updated tag list
    cur.execute("""
        SELECT t.name
        FROM episode_tags et
        JOIN tags t ON et.tag_id = t.id
        WHERE et.episode_key = %s
    """, (key,))
    updated = [r['name'] for r in cur.fetchall()]

    conn.close()
    return jsonify(tags=updated), 201


@app.route('/api/episode/<path:key>/tags/<string:tag>', methods=['DELETE'])
def remove_tag_from_episode(key, tag):
    conn = get_conn()
    cur  = conn.cursor()

    # 1) Find the tag ID (404 if it doesn't even exist)
    cur.execute(
        "SELECT id FROM tags WHERE name = %s",
        (tag,)
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        abort(404, description=f"Tag '{tag}' not found")

    tag_id = row['id']

    # 2) Remove the link from episode_tags
    cur.execute(
        "DELETE FROM episode_tags WHERE episode_key = %s AND tag_id = %s",
        (key, tag_id)
    )
    conn.commit()

    # 3) Return the updated tag list
    cur.execute("""
        SELECT t.name
        FROM episode_tags et
        JOIN tags t ON et.tag_id = t.id
        WHERE et.episode_key = %s
    """, (key,))
    updated = [r['name'] for r in cur.fetchall()]

    conn.close()
    return jsonify(tags=updated), 200
    
def get_conn():
    return psycopg2.connect(
        os.environ['DATABASE_URL'],
        cursor_factory=RealDictCursor
    )

@app.route("/api/episodes/replace-async", methods=["POST"])
def replace_episode_async():
    data = request.get_json() or {}
    key = data.get("key")
    if not key:
        return jsonify({"error": "key required"}), 400

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT series_id, episode_id FROM episodes WHERE key = %s", (key,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row or not row.get("series_id") or not row.get("episode_id"):
        return jsonify({"error": "no series/episode IDs for key"}), 404

    job_id = start_replace_job(key)

    def job_func():
        try:
            append_log(job_id, "Starting replace job…")
            grab_best_nzb(sonarr, row["series_id"], row["episode_id"])
            wait_for_sonarr_import(sonarr, row["series_id"], row["episode_id"], job_id=job_id, timeout=300)
        except Exception as e:
            append_log(job_id, f"Error: {e}")
            update_job(job_id, status="error", message=str(e))

    import threading
    threading.Thread(target=job_func, daemon=True).start()

    return jsonify({"job_id": job_id}), 202

@app.route("/api/job-status/<job_id>", methods=["GET"])
def api_job_status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    # Return recent subset
    return jsonify({
        "status": job.get("status"),
        "progress": job.get("progress"),
        "message": job.get("message"),
        "log": job.get("log", [])[-50:],
        "episode_key": job.get("episode_key")
    })

@app.route("/api/episodes/get_by_key", methods=["GET"])
def api_episodes_get_by_key():
    """
    Internal helper used by worker to fetch series_id/episode_id and code for a given key.
    Query param: ?key=...
    """
    key = request.args.get("key")
    if not key:
        return jsonify({"error": "key required"}), 400
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
      SELECT series_id, episode_id, code
        FROM episodes
       WHERE key = %s
    """, (key,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(row)

@app.route("/api/library-scan-status")
def library_scan_status():
    with jobs_lock:
        running_jobs = [job for job in jobs.values()
                        if job.get("status") == "running" and job.get("type") == "library_scan"]
        return jsonify({
            "running": len(running_jobs) > 0,
            "jobs": running_jobs
        })
        
if __name__ == '__main__':
    # serve on all interfaces on port 5001
    app.run(host='0.0.0.0', port=5001)
