import os
from flask import Flask, render_template
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

@app.route("/")
def index():
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
              pe.series_title   AS Series,
              pe.code           AS Code,
              COALESCE(string_agg(t.name, ', ' ORDER BY t.name), '')
                                 AS Tags
            FROM problematic_episodes pe
            JOIN mismatch_tracking mt   ON pe.key = mt.key
            LEFT JOIN episode_tags et   ON pe.episode_file_id = et.episode_file_id
            LEFT JOIN tags t            ON et.tag_id = t.id
            GROUP BY pe.series_title, pe.code
            ORDER BY pe.series_title, pe.code;
        """)
        rows = cur.fetchall()
    conn.close()

    # all_data now just has one entry, so the card-grid
    # will render one card titled "Episode Tag Report"
    return render_template("index.html", all_data={
        "Episode Tag Report": rows
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
