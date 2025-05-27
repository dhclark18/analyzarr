import os
from flask import Flask, render_template
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# Make sure this points at your Postgres instance
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

@app.route("/")
def index():
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
              et.series_title   AS series,
              et.code           AS code,
              COALESCE(
                string_agg(t.name, ', ' ORDER BY t.name),
              '')               AS tags
            FROM episode_tags et
            JOIN tags t
              ON et.tag_id = t.id
            GROUP BY
              et.series_title,
              et.code
            ORDER BY
              et.series_title,
              et.code;
        """)
        rows = cur.fetchall()
    conn.close()
    return render_template("index.html", rows=rows)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
