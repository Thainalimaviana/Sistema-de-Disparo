import os
import psycopg2
from db.db import DATABASE_URL, IS_POSTGRES

def check_schema():
    if not IS_POSTGRES:
        print("Not using Postgres.")
        return
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name = 'usuarios'")
    columns = cur.fetchall()
    print("Columns in 'usuarios' table:")
    for col in columns:
        print(col)
    conn.close()

if __name__ == "__main__":
    check_schema()
