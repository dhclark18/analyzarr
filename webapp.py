import os
import requests
from urllib.parse import quote, unquote

from flask import Flask, render_template
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

DATABASE_URL   = os.getenv("DATABASE_URL")
SONARR_URL     = os.getenv("SONARR_URL")
SONARR_API_KEY = os.getenv("SONARR_API_KEY")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def fetch_sonarr_series():
    headers = {"X-Api-Key": SONARR_API_KEY}
    r = requests.get(f"{SONARR_URL}/api/v3/series", headers=headers)
    r.raise_for_status()
    data = r.json()
    return [
        {
            "Title":     s["title"],
            "Seasons":   len(s.get("seasons", [])),
            "Monitored": "Yes" if s.get("monitored") else "No",
        }
        for s in data
    ]

@app.route("/")
def index():
    # 1) Get your Sonarr library
    try:
        library_rows = fetch_sonarr_series()
    except Exception as e:
        library_rows = [{"Title": f"Error: {e}", "Seasons": "", "Monitored": ""}]

    # 2) Find which series have tags in your DB
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT series_title
              FROM episode_tags;
        """)
        problem_titles = { r["series_title"] for r in cur.fetchall() }
    conn.close()

    # 3) Annotate each library row
    for row in library_rows:
        # True if this series has any problematic episodes
        row["has_problems"] = row["Title"] in problem_titles

    # 4) Render only the library cards
    return render_template("index.html", library_rows=library_rows)

@app.route("/series/<path:series_name>/tag/<int:tag_id>")
def tagged_episodes(series_name, tag_id):
    # decode the URL‐encoded series name
    series = unquote(series_name)
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
              code,
              tag_id
            FROM episode_tags
            WHERE series_title = %s
              AND tag_id      = %s
            ORDER BY code;
        """, (series, tag_id))
        rows = cur.fetchall()
    conn.close()
    return render_template(
        "tagged.html",
        series=series,
        tag_id=tag_id,
        rows=rows
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
