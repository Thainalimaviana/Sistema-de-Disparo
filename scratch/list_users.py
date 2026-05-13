import sqlite3
import os

SCRATCH_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRATCH_DIR)
DB_NAME = os.path.join(ROOT_DIR, 'db', 'sistema.db')

print(f"Tentando abrir: {DB_NAME}")

try:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, papel, ativo FROM usuarios")
    users = cursor.fetchall()
    print("Usuários cadastrados:")
    for u in users:
        print(u)
    conn.close()
except Exception as e:
    print(f"Erro: {e}")
