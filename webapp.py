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
    """Call Sonarr’s /api/series and normalize to a list of dicts."""
    headers = {"X-Api-Key": SONARR_API_KEY}
    r = requests.get(f"{SONARR_URL}/api/series", headers=headers)
    r.raise_for_status()
    data = r.json()
    out = []
    for s in data:
        out.append({
            "Title": s.get("title"),
            "Seasons": len(s.get("seasons", [])),
            "Monitored": "Yes" if s.get("monitored") else "No",
        })
    return out

@app.route("/")
def index():
    # --- Load your existing report ---
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
              pe.series_title AS Series,
              pe.code         AS Code,
              COALESCE(string_agg(t.name, ', ' ORDER BY t.name), '') AS Tags
            FROM episode_tags et
            JOIN tags t  ON et.tag_id = t.id
            JOIN episode_tags pe ON et.episode_file_id = pe.episode_file_id
            GROUP BY pe.series_title, pe.code
            ORDER BY pe.series_title, pe.code;
        """)
        report_rows = cur.fetchall()
    conn.close()

    # --- Fetch Sonarr library ---
    try:
        library_rows = fetch_sonarr_series()
    except Exception as e:
        library_rows = [{"Title": f"Error: {e}", "Seasons": "", "Monitored": ""}]

    # --- Build all_data so card-grid will render two cards ---
    all_data = {
        "Episode Tag Report": report_rows,
        "Library Series":     library_rows
    }

    return render_template("index.html", all_data=all_data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
