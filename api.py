#!/usr/bin/env python3
# api.py

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify
from flask import request, jsonify
import os
from analyzer import grab_best_nzb, SonarrClient

# initialize Sonarr client once
sonarr = SonarrClient(
    base_url=os.getenv("SONARR_URL"),
    api_key=os.getenv("SONARR_API_KEY"),
    timeout=10
)

@app.route('/api/episodes/replace', methods=['POST'])
def replace_episode():
    """
    Expects JSON { series_id: int, episode_id: int }.
    Calls grab_best_nzb (which handles deletion internally).
    """
    data = request.get_json() or {}
    series_id  = data.get("series_id")
    episode_id = data.get("episode_id")
    if series_id is None or episode_id is None:
        return jsonify({ "error": "series_id and episode_id required" }), 400

    try:
        grab_best_nzb(sonarr, series_id, episode_id)
        return jsonify({ "status": "ok" }), 200
    except Exception as e:
        return jsonify({ "error": str(e) }), 500

app = Flask(__name__)

def get_conn():
    return psycopg2.connect(
        os.environ['DATABASE_URL'],
        cursor_factory=RealDictCursor
    )

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

if __name__ == '__main__':
    # serve on all interfaces on port 5001
    app.run(host='0.0.0.0', port=5001)
