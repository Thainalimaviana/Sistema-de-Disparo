"""
Abstração de banco de dados: SQLite local / PostgreSQL no Render.
Detecta via variável de ambiente DATABASE_URL.
"""
import os
import re
import sqlite3

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_POSTGRES = bool(DATABASE_URL)

if IS_POSTGRES:
    import psycopg2
    import psycopg2.extras

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, 'sistema.db')
Row = sqlite3.Row


def adapt_sql(sql):
    """Converte SQL estilo SQLite para PostgreSQL automaticamente."""
    if not IS_POSTGRES:
        return sql

    result = sql.replace('?', '%s')

    # DDL
    if 'CREATE TABLE' in result.upper() or 'ALTER TABLE' in result.upper():
        result = re.sub(r'INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT', 'SERIAL PRIMARY KEY', result, flags=re.IGNORECASE)
        result = re.sub(r'\bDATETIME\b', 'TIMESTAMP', result, flags=re.IGNORECASE)

    # DATE(col) -> col::DATE (Suporta c.importado_em)
    result = re.sub(r"DATE\s*\(\s*([\w\.]+)\s*\)", r"\1::DATE", result, flags=re.IGNORECASE)
    
    # datetime('now') -> NOW()
    result = re.sub(r"datetime\s*\(\s*'now'\s*\)", "NOW()", result, flags=re.IGNORECASE)
    
    # datetime('now', '-3 hours') -> (NOW() - INTERVAL '3 hours')
    result = re.sub(r"datetime\s*\(\s*'now'\s*,\s*'-3 hours'\s*\)", "(NOW() - INTERVAL '3 hours')", result, flags=re.IGNORECASE)

    # date('now', '-7 days') -> (CURRENT_DATE - INTERVAL '7 days')
    result = re.sub(r"date\s*\(\s*'now'\s*,\s*'-7 days'\s*\)", "(CURRENT_DATE - INTERVAL '7 days')", result, flags=re.IGNORECASE)

    # strftime('%d/%m/%Y %H:%M', col, '-3 hours')
    result = re.sub(
        r"strftime\s*\(\s*'%d/%m/%Y %H:%M'\s*,\s*([\w\.]+)\s*,\s*'-3 hours'\s*\)",
        r"TO_CHAR(\1 - INTERVAL '3 hours', 'DD/MM/YYYY HH24:MI')", result, flags=re.IGNORECASE)
    # strftime('%d/%m/%Y %H:%M', col)
    result = re.sub(
        r"strftime\s*\(\s*'%d/%m/%Y %H:%M'\s*,\s*([\w\.]+)\s*\)",
        r"TO_CHAR(\1, 'DD/MM/YYYY HH24:MI')", result, flags=re.IGNORECASE)
    # strftime('%d/%m/%Y', col)
    result = re.sub(
        r"strftime\s*\(\s*'%d/%m/%Y'\s*,\s*([\w\.]+)\s*\)",
        r"TO_CHAR(\1, 'DD/MM/YYYY')", result, flags=re.IGNORECASE)
    # strftime('%H:%M', col)
    result = re.sub(
        r"strftime\s*\(\s*'%H:%M'\s*,\s*([\w\.]+)\s*\)",
        r"TO_CHAR(\1, 'HH24:MI')", result, flags=re.IGNORECASE)
    
    # INSERT OR IGNORE -> INSERT INTO ... ON CONFLICT DO NOTHING (Simplificado)
    # INSERT OR REPLACE -> INSERT INTO ... (Nota: ON CONFLICT seria melhor, mas aqui apenas evita erro de sintaxe)
    result = re.sub(r'INSERT\s+OR\s+IGNORE\s+INTO', 'INSERT INTO', result, flags=re.IGNORECASE)
    result = re.sub(r'INSERT\s+OR\s+REPLACE\s+INTO', 'INSERT INTO', result, flags=re.IGNORECASE)

    # Handlers para CURRENT_TIMESTAMP no SQLite que podem ser TIMESTAMP no PG
    result = result.replace('CURRENT_TIMESTAMP', 'NOW()')

    return result


class PgCursorWrapper:
    """Wrapper de cursor psycopg2 compatível com interface sqlite3."""

    def __init__(self, cursor):
        self._cursor = cursor
        self._lastrowid = None

    def execute(self, sql, params=None):
        sql = adapt_sql(sql)
        if params is not None:
            p = tuple(params) if not isinstance(params, tuple) else params
            self._cursor.execute(sql, p)
        else:
            self._cursor.execute(sql)
        self._lastrowid = None
        if sql.strip().upper().startswith('INSERT') and 'RETURNING' not in sql.upper():
            try:
                self._cursor.execute("SELECT lastval()")
                r = self._cursor.fetchone()
                self._lastrowid = r[0] if isinstance(r, tuple) else (r.get('lastval') if isinstance(r, dict) else None)
            except Exception:
                pass

    def executemany(self, sql, params_list):
        sql = adapt_sql(sql)
        count = 0
        for params in params_list:
            try:
                self._cursor.execute(sql, tuple(params))
                count += 1
            except Exception:
                pass
        self._rowcount_override = count

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        if hasattr(self, '_rowcount_override'):
            rc = self._rowcount_override
            del self._rowcount_override
            return rc
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description


class PgConnectionWrapper:
    """Wrapper de conexão psycopg2 compatível com interface sqlite3."""

    def __init__(self, conn):
        self._conn = conn
        self._row_factory = None

    @property
    def row_factory(self):
        return self._row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._row_factory = value

    def cursor(self):
        if self._row_factory:
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            cur = self._conn.cursor()
        return PgCursorWrapper(cur)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def connect(db_name=None):
    """Substituto direto para sqlite3.connect(). Retorna conexão SQLite ou PostgreSQL."""
    if IS_POSTGRES:
        return PgConnectionWrapper(psycopg2.connect(DATABASE_URL))
    else:
        return sqlite3.connect(db_name or DB_NAME)


def safe_add_column(cursor, table, col_name, col_type):
    """Adiciona coluna se não existir, compatível com ambos os bancos."""
    if IS_POSTGRES:
        col_type_pg = re.sub(r'\bDATETIME\b', 'TIMESTAMP', col_type, flags=re.IGNORECASE)
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_type_pg}")
    else:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass
