#!/usr/bin/env python3
# api.py

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, abort
from analyzer import grab_best_nzb, SonarrClient

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
          COUNT(*)                          AS "totalEpisodes",
          COUNT(DISTINCT series_id)         AS "totalShows",
          (SELECT COUNT(*)
             FROM episodes e
             JOIN episode_tags et
               ON e.key = et.episode_key
             JOIN tags t
               ON et.tag_id = t.id
              AND t.name = 'problematic-episode'
          )                                  AS "totalMismatches",
          COUNT(*) FILTER (WHERE missing_title) AS "totalMissingTitles"
        FROM episodes;
    """)
    stats = cur.fetchone()   # this is now a dict
    cur.close()
    conn.close()
    return stats
    
@app.route('/api/stats')
def stats():
    return jsonify(compute_stats())  
    
@app.route('/api/episodes/replace', methods=['POST'])
def replace_episode():
    """
    Expects JSON { key: <string> } where key is your episodes.key.
    Looks up series_id & episode_id in the DB, then calls grab_best_nzb.
    """
    data = request.get_json() or {}
    key = data.get("key")
    if not key:
        return jsonify({ "error": "key required" }), 400

    # pull the IDs out of your episodes table
    conn = get_conn()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
      SELECT series_id, episode_id
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
        return jsonify({ "status": "ok" }), 200
    except Exception as e:
        return jsonify({ "error": str(e) }), 500

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
    
if __name__ == '__main__':
    # serve on all interfaces on port 5001
    app.run(host='0.0.0.0', port=5001)
