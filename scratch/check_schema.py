import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, 'db', 'sistema.db')

conn = sqlite3.connect(DB_NAME)
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(usuarios);")
columns = cursor.fetchall()
conn.close()

for col in columns:
    print(col)
