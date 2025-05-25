import os
from flask import Flask, render_template
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

@app.route("/")
def index():
    conn = get_db_connection()
    with conn.cursor() as cur:
        # 1) get all user tables in public schema
        cur.execute("""
            SELECT table_name
              FROM information_schema.tables
             WHERE table_schema = 'public'
               AND table_type   = 'BASE TABLE'
            ORDER BY table_name;
        """)
        tables = [row['table_name'] for row in cur.fetchall()]

        all_data = {}
        # 2) for each table, fetch all rows
        for tbl in tables:
            cur.execute(
                sql.SQL("SELECT * FROM {}").format(sql.Identifier(tbl))
            )
            all_data[tbl] = cur.fetchall()

    conn.close()
    return render_template("index_all.html", all_data=all_data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
