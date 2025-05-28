import os
import requests
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
    # 1) Episode Tag Report from raw tag_id values
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
              series_title       AS series,
              code,
              COALESCE(
                string_agg(tag_id::text, ', ' ORDER BY tag_id),
              '')               AS tags
            FROM episode_tags
            GROUP BY series_title, code
            ORDER BY series_title, code;
        """)
        report_rows = cur.fetchall()
    conn.close()

    # 2) Full Sonarr library
    try:
        library_rows = fetch_sonarr_series()
    except Exception as e:
        library_rows = [{"Title": f"Error: {e}", "Seasons": "", "Monitored": ""}]

    all_data = {
        "Episode Tag Report": report_rows,
        "Library Series":     library_rows
    }

    return render_template("index.html", all_data=all_data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
