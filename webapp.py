import os
from flask import Flask, render_template
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# DATABASE_URL should point at your postgres container/service:
# e.g. postgresql://sonarr:sonarr@postgres:5432/sonarr_checker
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

@app.route("/")
def index():
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
              key,
              count,
              last_mismatch,
            FROM mismatch_tracking
            ORDER BY key;
        """)
        rows = cur.fetchall()
    conn.close()
    return render_template("index.html", rows=rows)

if __name__ == "__main__":
    # dev server; replace with Gunicorn/etc. in production
    app.run(host="0.0.0.0", port=5000, debug=True)
