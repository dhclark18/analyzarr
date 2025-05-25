import os
from flask import Flask, render_template
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# Configure via environment variable:
#   export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

@app.route("/")
def index():
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM your_table_name ORDER BY id;")
        rows = cur.fetchall()   # list of dicts if using RealDictCursor
    conn.close()
    return render_template("index.html", rows=rows)

if __name__ == "__main__":
    # For development only; use Gunicorn or uWSGI in production
    app.run(host="0.0.0.0", port=5000, debug=True)
