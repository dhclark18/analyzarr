#!/usr/bin/env python3
# api.py

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify

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

@app.route('/api/series/<int:series_id>/episodes')
def series_episodes(series_id):
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
          e.expected_title AS expectedTitle,
          e.actual_title   AS actualTitle,
          e.confidence AS confidence,
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
