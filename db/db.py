"""
Módulo unificado de banco de dados.
Abstração SQLite (local) / PostgreSQL (Render via DATABASE_URL).
"""
import os
import re
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, 'sistema.db')
Row = sqlite3.Row
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_POSTGRES = bool(DATABASE_URL)

if IS_POSTGRES:
    import psycopg2
    import psycopg2.extras

def adapt_sql(sql):
    """Converte SQL estilo SQLite para PostgreSQL automaticamente."""
    if not IS_POSTGRES:
        return sql
    
    result = sql.replace('?', '%s')
    
    # 1. Ajustes de Tipos e PK
    if 'CREATE TABLE' in result.upper() or 'ALTER TABLE' in result.upper():
        result = re.sub(r'INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT', 'SERIAL PRIMARY KEY', result, flags=re.IGNORECASE)
        result = re.sub(r'\bDATETIME\b', 'TIMESTAMP', result, flags=re.IGNORECASE)
    
    # 2. Funções de Data
    result = re.sub(r"DATE\s*\(\s*([\w\.]+)\s*\)", r"\1::DATE", result, flags=re.IGNORECASE)
    result = re.sub(r"datetime\s*\(\s*'now'\s*\)", "NOW()", result, flags=re.IGNORECASE)
    result = re.sub(r"datetime\s*\(\s*'now'\s*,\s*'-3 hours'\s*\)", "NOW() - INTERVAL '3 hours'", result, flags=re.IGNORECASE)

    # 3. Tratar INSERT OR IGNORE -> ON CONFLICT DO NOTHING
    if "INSERT OR IGNORE INTO" in result.upper():
        result = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO\s+([\w\d_]+)", r"INSERT INTO \1", result, flags=re.IGNORECASE)
        if "ON CONFLICT" not in result.upper():
            result = result.rstrip(';') + " ON CONFLICT DO NOTHING"

    # 4. Tratar INSERT OR REPLACE -> ON CONFLICT DO UPDATE
    if "INSERT OR REPLACE INTO" in result.upper():
        result = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO\s+([\w\d_]+)", r"INSERT INTO \1", result, flags=re.IGNORECASE)
        if "configuracoes" in result.lower():
            result = result.rstrip(';') + " ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor"
        elif "chat_ultima_leitura" in result.lower():
            result = result.rstrip(';') + " ON CONFLICT (usuario_username, canal) DO UPDATE SET lido_em = EXCLUDED.lido_em"
        elif "canais" in result.lower():
            result = result.rstrip(';') + " ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome, privacidade = EXCLUDED.privacidade, criado_por = EXCLUDED.criado_por"

    return result

class PgCursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor
        self._lastrowid = None
        
    def execute(self, sql, params=None):
        sql = adapt_sql(sql)
        
        # Executa o comando principal
        if params is not None:
            self._cursor.execute(sql, params)
        else:
            self._cursor.execute(sql)
            
        # Tenta pegar o lastval sem quebrar a transação se não houver sequence
        if sql.strip().upper().startswith('INSERT') and self._cursor.rowcount > 0:
            try:
                self._cursor.execute("SAVEPOINT get_lastval")
                self._cursor.execute("SELECT lastval()")
                self._lastrowid = self._cursor.fetchone()[0]
                self._cursor.execute("RELEASE SAVEPOINT get_lastval")
            except Exception:
                self._cursor.execute("ROLLBACK TO SAVEPOINT get_lastval")
                self._lastrowid = None

    def fetchone(self): return self._cursor.fetchone()
    def fetchall(self): return self._cursor.fetchall()
    
    @property
    def lastrowid(self): return self._lastrowid
    
    @property
    def description(self): return self._cursor.description
    
    @property
    def rowcount(self): return self._cursor.rowcount

class PgConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn
        self._row_factory = None
    @property
    def row_factory(self): return self._row_factory
    @row_factory.setter
    def row_factory(self, value): self._row_factory = value
    def cursor(self):
        if self._row_factory:
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            cur = self._conn.cursor()
        return PgCursorWrapper(cur)
    def commit(self): self._conn.commit()
    def rollback(self): self._conn.rollback()
    def close(self): self._conn.close()

def connect(db_name=None):
    """Substituto direto para sqlite3.connect(). Retorna conexão SQLite ou PostgreSQL."""
    if IS_POSTGRES:
        return PgConnectionWrapper(psycopg2.connect(DATABASE_URL))
    return sqlite3.connect(db_name or DB_NAME)

def safe_add_column(cursor, table, column, definition):
    """Adiciona uma coluna à tabela se ela não existir (SQLite)."""
    cursor.execute(f"PRAGMA table_info({table})")
    colunas = [info[1] for info in cursor.fetchall()]
    if column not in colunas:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        except Exception as e:
            print(f"Erro ao adicionar coluna {column} na tabela {table}: {e}")

def init_db():
    """Inicializa o banco de dados e cria as tabelas se não existirem."""
    conn = connect()
    cursor = conn.cursor()
    
    _serial_pk = "SERIAL PRIMARY KEY" if IS_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
    _ts = "TIMESTAMP" if IS_POSTGRES else "DATETIME"
    _blob = "BYTEA" if IS_POSTGRES else "BLOB"
    
    # 1. Usuários
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS usuarios (
            id {_serial_pk}, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
            nome TEXT DEFAULT '', email TEXT DEFAULT '', papel TEXT DEFAULT 'vendedor',
            localizacao TEXT DEFAULT '', lat REAL, lng REAL, ip TEXT, ativo INTEGER DEFAULT 1,
            criado_em {_ts}, foto TEXT DEFAULT ''
        )
    ''')
    
    # 2. Configurações (A TABELA QUE FALTAVA E CAUSAVA O CRASH)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS configuracoes (
            chave TEXT PRIMARY KEY,
            valor TEXT
        )
    ''')

    # 3. Demais tabelas do sistema
    cursor.execute(f"CREATE TABLE IF NOT EXISTS comunicados (id {_serial_pk}, titulo TEXT, tipo TEXT, mensagem TEXT, autor TEXT, fixado INTEGER DEFAULT 0, lido_por TEXT DEFAULT '', arquivado_por TEXT DEFAULT '', criado_em {_ts} DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute(f"CREATE TABLE IF NOT EXISTS bancos (id {_serial_pk}, nome TEXT, codigo TEXT, ativo BOOLEAN DEFAULT 1, data_inativacao {_ts}, criado_em {_ts} DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute(f"CREATE TABLE IF NOT EXISTS solicitacoes_leads (id {_serial_pk}, vendedor TEXT, quantidade_solicitada INTEGER, banco_id INTEGER, banco_nome TEXT, observacao TEXT, status TEXT DEFAULT 'pendente', quantidade_enviada INTEGER DEFAULT 0, atualizado_em {_ts}, criado_em {_ts} DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute(f"CREATE TABLE IF NOT EXISTS clientes (id {_serial_pk}, nome TEXT, cpf TEXT, telefone1 TEXT, telefone2 TEXT, telefone3 TEXT, telefone4 TEXT, margem REAL, margem_verificada REAL, whatsapp TEXT, sexo TEXT, idade INTEGER, rua TEXT, bairro TEXT, cep TEXT, cidade TEXT, estado TEXT, banco_id INTEGER, banco_nome TEXT, lote_id INTEGER, status TEXT DEFAULT 'pendente', vendedor_id INTEGER, vendedor_nome TEXT, importado_em {_ts} DEFAULT CURRENT_TIMESTAMP, atribuido_em {_ts}, data_tabulacao {_ts}, bancos_elegiveis TEXT, observacao TEXT)")
    cursor.execute(f"CREATE TABLE IF NOT EXISTS vendedores (id {_serial_pk}, nome TEXT, username TEXT, telefone TEXT, ativo INTEGER DEFAULT 1)")
    cursor.execute(f"CREATE TABLE IF NOT EXISTS lotes_importados (id {_serial_pk}, nome_arquivo TEXT, banco_id INTEGER, banco_nome TEXT, quantidade_leads INTEGER, importado_por TEXT, arquivo_blob {_blob}, criado_em {_ts} DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute(f"CREATE TABLE IF NOT EXISTS scripts (id {_serial_pk}, titulo TEXT, categoria TEXT, conteudo TEXT, publicado INTEGER DEFAULT 0, atualizado_em {_ts} DEFAULT CURRENT_TIMESTAMP, fixado INTEGER DEFAULT 0)")
    cursor.execute(f"CREATE TABLE IF NOT EXISTS logs (id {_serial_pk}, usuario TEXT, acao TEXT, detalhe TEXT, ip TEXT, localizacao TEXT, criado_em {_ts} DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute(f"CREATE TABLE IF NOT EXISTS canais (id TEXT PRIMARY KEY, nome TEXT, privacidade TEXT, criado_por TEXT, criado_em {_ts} DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute(f"CREATE TABLE IF NOT EXISTS membros_canal (canal_id TEXT, usuario_username TEXT, UNIQUE(canal_id, usuario_username))")
    cursor.execute(f"CREATE TABLE IF NOT EXISTS mensagens_chat (id {_serial_pk}, remetente TEXT, nome_exibicao TEXT, destinatario TEXT, mensagem TEXT, enviado_em {_ts} DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute(f"CREATE TABLE IF NOT EXISTS conversas_fixadas (id {_serial_pk}, usuario_username TEXT NOT NULL, target_id TEXT NOT NULL, criado_em {_ts} DEFAULT CURRENT_TIMESTAMP, UNIQUE(usuario_username, target_id))")
    cursor.execute(f"CREATE TABLE IF NOT EXISTS chat_ultima_leitura (id {_serial_pk}, usuario_username TEXT NOT NULL, canal TEXT NOT NULL DEFAULT 'geral', lido_em {_ts} DEFAULT CURRENT_TIMESTAMP, UNIQUE(usuario_username, canal))")

    # Inserções Iniciais Básicas
    cursor.execute("INSERT OR IGNORE INTO configuracoes (chave, valor) VALUES ('dist_auto_ativa', '0')")
    cursor.execute("INSERT OR IGNORE INTO configuracoes (chave, valor) VALUES ('dist_auto_qtd', '10')")

    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO usuarios (username, password, papel, nome, email, ativo) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, ('admin@consigtech.com', 'senha123', 'admin', 'Administrador', 'admin@consigtech.com', True))
    
    conn.commit()
    conn.close()
    
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        # Incluímos 'nome', 'email' e 'ativo' para evitar erros de restrição NOT NULL em bancos antigos
        cursor.execute("""
            INSERT INTO usuarios (username, password, papel, nome, email, ativo) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, ('admin@consigtech.com', 'senha123', 'admin', 'Administrador', 'admin@consigtech.com', True))
    
    conn.commit()
    conn.close()

def obter_configuracao(chave, padrao=None):
    """Retorna o valor de uma configuração."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT valor FROM configuracoes WHERE chave = ?", (chave,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else padrao

def salvar_configuracao(chave, valor):
    """Salva ou atualiza uma configuração."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO configuracoes (chave, valor) VALUES (?, ?)", (chave, str(valor)))
    conn.commit()
    conn.close()

def verificar_login(username, password):
    """Verifica login e retorna os dados do usuário (id, username, papel, nome, foto) se válido."""
    conn = connect()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, username, papel, nome, foto FROM usuarios WHERE username = ? AND password = ?", (username, password))
        user = cursor.fetchone()
    except Exception as e:
        if "no such column: foto" in str(e):
            # Fallback para bancos sem a coluna foto ainda. No Postgres, resetamos a transação.
            pass
        conn.close()
        raise e
    conn.close()
    if user:
        return {
            'id': user[0], 
            'username': user[1], 
            'papel': user[2], 
            'nome': user[3],
            'foto': user[4] if len(user) > 4 else ''
        }
    return None

def salvar_comunicado(titulo, tipo, mensagem, autor, fixado=0):
    """Salva um comunicado no banco de dados."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO comunicados (titulo, tipo, mensagem, autor, fixado) VALUES (?, ?, ?, ?, ?)",
        (titulo, tipo, mensagem, autor, fixado)
    )
    conn.commit()
    conn.close()

def buscar_comunicados():
    """Retorna todos os comunicados ordenados do mais recente."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id, titulo, tipo, mensagem, autor, criado_em, fixado, lido_por, arquivado_por FROM comunicados ORDER BY fixado DESC, criado_em DESC")
    rows = cursor.fetchall()
    conn.close()
    
    comunicados = []
    for r in rows:
        criado_em = r[5]
        # Se for um objeto datetime (comum no Postgres/Render), converte para ISO string
        if hasattr(criado_em, 'isoformat'):
            # Se não tiver timezone, adicionamos 'Z' (UTC) pois o DB salva em UTC
            if criado_em.tzinfo is None:
                criado_em = criado_em.isoformat() + 'Z'
            else:
                criado_em = criado_em.isoformat()
        elif isinstance(criado_em, str):
            # No SQLite vem como "YYYY-MM-DD HH:MM:SS", convertemos para ISO UTC
            criado_em = criado_em.replace(' ', 'T') + 'Z'
        
        comunicados.append({
            'id': r[0], 
            'titulo': r[1], 
            'tipo': r[2], 
            'mensagem': r[3], 
            'autor': r[4], 
            'criado_em': criado_em, 
            'fixado': r[6], 
            'lido_por': r[7], 
            'arquivado_por': r[8] or ''
        })
    return comunicados

def editar_comunicado(com_id, titulo, tipo, mensagem, fixado=0):
    """Atualiza as informações de um comunicado existente."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE comunicados SET titulo = ?, tipo = ?, mensagem = ?, fixado = ? WHERE id = ?",
        (titulo, tipo, mensagem, fixado, com_id)
    )
    conn.commit()
    conn.close()

def deletar_comunicado(com_id):
    """Deleta um comunicado do banco de dados."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM comunicados WHERE id = ?", (com_id,))
    conn.commit()
    conn.close()

def alternar_fixar_comunicado(com_id):
    """Alterna o status de fixado de um comunicado."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT fixado FROM comunicados WHERE id = ?", (com_id,))
    row = cursor.fetchone()
    if row:
        novo_status = 0 if row[0] in (1, True, 't', 'true') else 1
        cursor.execute("UPDATE comunicados SET fixado = ? WHERE id = ?", (novo_status, com_id))
        conn.commit()
    conn.close()

def marcar_todos_lidos_usuario(username):
    """Adiciona o username na coluna lido_por de todos os comunicados."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id, lido_por FROM comunicados")
    rows = cursor.fetchall()
    for r in rows:
        c_id = r[0]
        lido_por = r[1] or ''
        if username not in lido_por:
            novo_lido_por = lido_por + ',' + username if lido_por else username
            cursor.execute("UPDATE comunicados SET lido_por = ? WHERE id = ?", (novo_lido_por, c_id))
    conn.commit()
    conn.close()

def marcar_lido_usuario(com_id, username):
    """Marca um comunicado específico como lido pelo usuário."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT lido_por FROM comunicados WHERE id = ?", (com_id,))
    row = cursor.fetchone()
    if row:
        lido_por = row[0] or ''
        if username not in lido_por:
            novo = lido_por + ',' + username if lido_por else username
            cursor.execute("UPDATE comunicados SET lido_por = ? WHERE id = ?", (novo, com_id))
            conn.commit()
    conn.close()

def arquivar_comunicado_usuario(com_id, username):
    """Adiciona o username na coluna arquivado_por do comunicado."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT arquivado_por FROM comunicados WHERE id = ?", (com_id,))
    row = cursor.fetchone()
    if row:
        arquivado_por = row[0] or ''
        if username not in arquivado_por:
            novo = arquivado_por + ',' + username if arquivado_por else username
            cursor.execute("UPDATE comunicados SET arquivado_por = ? WHERE id = ?", (novo, com_id))
            conn.commit()
    conn.close()

def desarquivar_comunicado_usuario(com_id, username):
    """Remove o username da coluna arquivado_por do comunicado."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT arquivado_por FROM comunicados WHERE id = ?", (com_id,))
    row = cursor.fetchone()
    if row:
        arquivado_por = row[0] or ''
        lista = [u.strip() for u in arquivado_por.split(',') if u.strip() and u.strip() != username]
        novo = ','.join(lista)
        cursor.execute("UPDATE comunicados SET arquivado_por = ? WHERE id = ?", (novo, com_id))
        conn.commit()
    conn.close()

def listar_bancos(apenas_ativos=True):
    """Retorna os bancos cadastrados."""
    conn = connect()
    cursor = conn.cursor()
    fmt_criado = "TO_CHAR(criado_em, 'DD/MM/YYYY')" if IS_POSTGRES else "strftime('%d/%m/%Y', criado_em)"
    fmt_inativacao = "TO_CHAR(data_inativacao, 'DD/MM/YYYY')" if IS_POSTGRES else "strftime('%d/%m/%Y', data_inativacao)"
    
    if apenas_ativos:
        cursor.execute(f"SELECT id, nome, codigo, ativo, {fmt_criado} as d1, {fmt_inativacao} as d2 FROM bancos WHERE ativo = ? ORDER BY nome", (True,))
    else:
        cursor.execute(f"SELECT id, nome, codigo, ativo, {fmt_criado} as d1, {fmt_inativacao} as d2 FROM bancos ORDER BY ativo DESC, nome")
    rows = cursor.fetchall()
    conn.close()
    return [{'id': r[0], 'nome': r[1], 'codigo': r[2], 'status': bool(r[3]), 'data_criacao': r[4], 'data_inativacao': r[5] or '-'} for r in rows]

def alternar_status_banco(banco_id):
    """Ativa ou inativa um banco (soft disable)."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT ativo FROM bancos WHERE id = ?", (banco_id,))
    row = cursor.fetchone()
    if row:
        esta_ativo = row[0] in (1, True, 't', 'true')
        novo_status = False if esta_ativo else True
        if not novo_status:
            # Inativando: setar data_inativacao
            cursor.execute("UPDATE bancos SET ativo = ?, data_inativacao = CURRENT_TIMESTAMP WHERE id = ?", (novo_status, banco_id))
        else:
            # Ativando: limpar data_inativacao
            cursor.execute("UPDATE bancos SET ativo = ?, data_inativacao = NULL WHERE id = ?", (novo_status, banco_id))
    conn.commit()
    conn.close()

def obter_banco_por_id(banco_id):
    """Retorna os dados de um banco pelo seu ID."""
    conn = connect()
    conn.row_factory = Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, codigo, ativo, data_inativacao FROM bancos WHERE id = ?", (banco_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def adicionar_banco(nome, codigo=''):
    """Adiciona um novo banco como ativo. Se já existir inativo, reativa."""
    conn = connect()
    cursor = conn.cursor()
    
    # Verifica se já existe um banco com este nome
    cursor.execute("SELECT id, ativo FROM bancos WHERE nome = ?", (nome,))
    row = cursor.fetchone()
    
    if row:
        banco_id, ativo = row[0], row[1]
        if ativo:
            conn.close()
            raise ValueError(f"O banco '{nome}' já está cadastrado e ativo.")
        else:
            # Reativa
            cursor.execute("UPDATE bancos SET ativo = ?, data_inativacao = NULL WHERE id = ?", (True, banco_id))
            conn.commit()
            conn.close()
            return banco_id
            
    cursor.execute("INSERT INTO bancos (nome, codigo, ativo, data_inativacao) VALUES (?, ?, ?, NULL)", (nome, codigo, True))
    conn.commit()
    novo_id = cursor.lastrowid
    conn.close()
    return novo_id

def remover_banco(banco_id):
    """Desativa (remove) um banco pelo ID."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bancos WHERE id = ?", (banco_id,))
    conn.commit()
    conn.close()

# ── Solicitações de Leads ──

def criar_solicitacao_leads(vendedor, quantidade, banco_id=None, banco_nome='', observacao=''):
    """Cria uma nova solicitação de leads pelo vendedor."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO solicitacoes_leads 
           (vendedor, quantidade_solicitada, banco_id, banco_nome, observacao) 
           VALUES (?, ?, ?, ?, ?)""",
        (vendedor, quantidade, banco_id, banco_nome, observacao)
    )
    conn.commit()
    novo_id = cursor.lastrowid
    conn.close()
    return novo_id

def listar_solicitacoes(status=None):
    """Retorna solicitações de leads. Se status=None, retorna todas."""
    conn = connect()
    cursor = conn.cursor()
    if status:
        cursor.execute(
            "SELECT * FROM solicitacoes_leads WHERE status = ? ORDER BY criado_em DESC",
            (status,)
        )
    else:
        cursor.execute("SELECT * FROM solicitacoes_leads ORDER BY criado_em DESC")
    rows = cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]

def aprovar_solicitacao(sol_id, quantidade_enviada, aprovado_por):
    """Admin aprova e define quantos leads serão enviados."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE solicitacoes_leads 
           SET status='aprovada', quantidade_enviada=?, 
               atualizado_em=CURRENT_TIMESTAMP, observacao=?
           WHERE id=?""",
        (quantidade_enviada, f'Aprovado por {aprovado_por}', sol_id)
    )
    conn.commit()
    conn.close()

def rejeitar_solicitacao(sol_id, motivo=''):
    """Admin rejeita uma solicitação."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE solicitacoes_leads 
           SET status='rejeitada', atualizado_em=CURRENT_TIMESTAMP, observacao=?
           WHERE id=?""",
        (motivo or 'Rejeitado pelo administrador', sol_id)
    )
    conn.commit()
    conn.close()

# ── Estatísticas Dinâmicas ──

def get_clientes_por_banco():
    """Retorna contagem de clientes pendentes agrupada por banco e data de importação (Lote/Base)."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.id, b.nome, DATE(c.importado_em) as data_imp, COUNT(c.id) as total
        FROM bancos b
        LEFT JOIN clientes c ON b.id = c.banco_id AND c.status = 'pendente'
        GROUP BY b.id, b.nome, DATE(c.importado_em)
        ORDER BY b.nome, data_imp DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for r in rows:
        b_id = r[0]
        b_nome = r[1]
        dt_imp = r[2]
        total = r[3]
        
        # Correção para o objeto datetime.date retornado no Postgres
        if dt_imp and not isinstance(dt_imp, str):
            dt_imp = dt_imp.isoformat()

        identificador = f"{b_id}|{dt_imp}" if dt_imp else str(b_id)
        
        # Formatar exibição
        nome_exibicao = b_nome
        data_exibicao = "Base Única"
        if dt_imp:
            try:
                parts = dt_imp.split('-')
                data_exibicao = f"Lote de {parts[2]}/{parts[1]}/{parts[0]}"
                nome_exibicao = f"{b_nome} ({parts[2]}/{parts[1]}/{parts[0]})"
            except:
                data_exibicao = f"Lote de {dt_imp}"
                nome_exibicao = f"{b_nome} ({dt_imp})"
                
        result.append({
            'banco_id': identificador,
            'banco_nome_puro': b_nome,
            'banco_data': data_exibicao,
            'banco_nome': nome_exibicao,
            'total': total
        })
    return result

# ── Vendedores ──

def listar_vendedores(apenas_ativos=True):
    """Lista usuários que possuem o papel de vendedor."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, username, ativo FROM usuarios WHERE papel='vendedor' ORDER BY nome")
    rows = cursor.fetchall()
    conn.close()
    return [{'id': r[0], 'nome': r[1] or r[2], 'username': r[2], 'ativo': r[3]} for r in rows]

def adicionar_vendedor(nome, username='', telefone=''):
    """Adiciona um novo vendedor."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO vendedores (nome, username, telefone, ativo) VALUES (?, ?, ?, ?)", (nome, username, telefone, 1))
    conn.commit()
    novo_id = cursor.lastrowid
    conn.close()
    return novo_id

def remover_vendedor(vendedor_id):
    """Desativa um vendedor pelo ID."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE vendedores SET ativo=0 WHERE id=?", (vendedor_id,))
    conn.commit()
    conn.close()

# ── Distribuição de Clientes ──

def obter_atividades_recentes(limite=5, data_inicio=None, data_fim=None, vendedor_id=None):
    """Retorna os últimos clientes adicionados/atualizados para o dashboard com filtro de data."""
    conn = connect()
    cursor = conn.cursor()
    
    where_clause = " WHERE (vendedor_nome IS NOT NULL AND vendedor_nome != '')"
    params = []
    
    if vendedor_id is not None:
        where_clause += " AND vendedor_id = ?"
        params.append(vendedor_id)
        
    if data_inicio:
        where_clause += " AND importado_em >= ?"
        params.append(f"{data_inicio} 00:00:00")
    if data_fim:
        where_clause += " AND importado_em <= ?"
        params.append(f"{data_fim} 23:59:59")
        
    query = f"""
        SELECT vendedor_nome, nome, banco_nome, margem, status, importado_em 
        FROM clientes 
        {where_clause}
        ORDER BY importado_em DESC LIMIT ?
    """
    params.append(limite)
    
    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    conn.close()
    
    atividades = []
    for r in rows:
        margem_float = r[3] if r[3] is not None else 0.0
        margem_str = f"R$ {margem_float:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        
        status_val = r[4] or 'pendente'
        
        atividades.append({
            'vendedor': r[0],
            'cliente': r[1],
            'banco': r[2] or 'N/A',
            'margem': margem_str,
            'status': status_val,
            'data': r[5]
        })
    return atividades

def obter_dashboard_stats(data_inicio=None, data_fim=None, vendedor_id=None):
    """Retorna as estatísticas reais para os cards do dashboard com filtro de data e vendedor."""
    conn = connect()
    cursor = conn.cursor()
    
    where_clause = " WHERE 1=1"
    params = []
    
    if vendedor_id is not None:
        where_clause += " AND vendedor_id = ?"
        params.append(vendedor_id)
        
    if data_inicio:
        where_clause += " AND importado_em >= ?"
        params.append(f"{data_inicio} 00:00:00")
    if data_fim:
        where_clause += " AND importado_em <= ?"
        params.append(f"{data_fim} 23:59:59")

    # 1. Total de clientes
    cursor.execute(f"SELECT COUNT(*) FROM clientes {where_clause}", tuple(params))
    total_clientes = cursor.fetchone()[0]
    
    # 2. Elegíveis
    where_elegivel = where_clause + " AND LOWER(status) LIKE '%elegível%' AND LOWER(status) NOT LIKE '%não%'"
    cursor.execute(f"SELECT COUNT(*) FROM clientes {where_elegivel}", tuple(params))
    elegiveis = cursor.fetchone()[0]
    
    # 3. Não Elegíveis
    where_nao_elegivel = where_clause + " AND (LOWER(status) LIKE '%não elegível%' OR LOWER(status) LIKE '%rejeitado%')"
    cursor.execute(f"SELECT COUNT(*) FROM clientes {where_nao_elegivel}", tuple(params))
    nao_elegiveis = cursor.fetchone()[0]

    # 4. Não Distribuídos (Pendentes na base geral)
    where_pendente = where_clause + " AND vendedor_id IS NULL"
    cursor.execute(f"SELECT COUNT(*) FROM clientes {where_pendente}", tuple(params))
    nao_distribuidos = cursor.fetchone()[0]
    
    conn.close()
    
    # 4. Taxa de conversão
    total_avaliados = elegiveis + nao_elegiveis
    taxa_conversao = 0
    if total_avaliados > 0:
        taxa_conversao = (elegiveis / total_avaliados) * 100
        
    return {
        'contatos': total_clientes,
        'elegiveis': elegiveis,
        'nao_elegiveis': nao_elegiveis,
        'nao_distribuidos': nao_distribuidos,
        'taxa_conversao': round(taxa_conversao, 1)
    }

def obter_ranking_bancos(limit=5, data_inicio=None, data_fim=None, vendedor_id=None):
    """Retorna os bancos com maior volume de margem cadastrada no período."""
    conn = connect()
    cursor = conn.cursor()
    
    where_clause = ""
    params = []
    
    if vendedor_id is not None:
        where_clause += " AND c.vendedor_id = ?"
        params.append(vendedor_id)
        
    if data_inicio:
        where_clause += " AND c.importado_em >= ?"
        params.append(f"{data_inicio} 00:00:00")
    if data_fim:
        where_clause += " AND c.importado_em <= ?"
        params.append(f"{data_fim} 23:59:59")
    
    query = f"""
        SELECT 
            b.nome, 
            COUNT(c.id) as total_clientes,
            SUM(CASE WHEN (c.status LIKE '%eleg%' OR c.status LIKE '%Eleg%') AND c.status NOT LIKE '%n_o%' AND c.status NOT LIKE '%N_o%' AND c.status NOT LIKE '%nao%' AND c.status NOT LIKE '%Nao%' THEN 1 ELSE 0 END) as elegiveis
        FROM bancos b
        LEFT JOIN clientes c ON b.id = c.banco_id {where_clause}
        WHERE b.ativo = ?
        GROUP BY b.id, b.nome
    """
    
    params.append(True)
    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    conn.close()
    
    ranking = []
    for r in rows:
        nome = r[0]
        total = r[1] or 0
        elegiveis = r[2] or 0
        pct = round((elegiveis / total * 100), 1) if total > 0 else 0
        ranking.append({
            'nome': nome,
            'total': total,
            'elegiveis': elegiveis,
            'porcentagem': pct
        })
        
    # Ordenar por porcentagem (decrescente), desempatando por quantidade de elegiveis
    ranking.sort(key=lambda x: (x['porcentagem'], x['elegiveis']), reverse=True)
    return ranking[:limit]

def distribuir_clientes(vendedor_id, vendedor_nome, banco_id, quantidade):
    """Distribui N clientes pendentes de um banco ou lote específico para um vendedor."""
    conn = connect()
    cursor = conn.cursor()
    
    query = "SELECT id FROM clientes WHERE (vendedor_id IS NULL OR status = 'pendente') AND status != 'finalizado'"
    params = []
    
    if banco_id:
        if isinstance(banco_id, str) and '|' in banco_id:
            b_id, data_imp = banco_id.split('|')
            query += " AND banco_id = ? AND DATE(importado_em) = ?"
            params.extend([b_id, data_imp])
        else:
            query += " AND banco_id = ?"
            params.append(banco_id)
            
    query += " LIMIT ?"
    params.append(quantidade)
    
    cursor.execute(query, tuple(params))
    ids = [r[0] for r in cursor.fetchall()]
    if ids:
        placeholders = ','.join('?' * len(ids))
        cursor.execute(
            f"""UPDATE clientes SET status='atribuido', vendedor_id=?, vendedor_nome=?,
                atribuido_em=CURRENT_TIMESTAMP WHERE id IN ({placeholders})""",
            [vendedor_id, vendedor_nome] + ids
        )
    conn.commit()
    conn.close()
    return len(ids)

def recolher_clientes_vendedor(vendedor_id):
    """Remove todos os leads pendentes/atribuídos de um vendedor, voltando-os para a base comum."""
    conn = connect()
    cursor = conn.cursor()
    # Apenas recolhe leads que ainda não foram FINALIZADOS (status 'atribuido' ou 'pendente' com vendedor)
    cursor.execute("""
        UPDATE clientes 
        SET status = 'pendente', vendedor_id = NULL, vendedor_nome = NULL, atribuido_em = NULL
        WHERE vendedor_id = ? AND status IN ('atribuido', 'pendente')
    """, (vendedor_id,))
    total = cursor.rowcount
    conn.commit()
    conn.close()
    return total

def obter_usuario_por_username(username):
    """Retorna o dicionário com dados do usuário dado seu username."""
    conn = connect()
    conn.row_factory = Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE username=?", (username,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def salvar_clientes_lote(clientes_dados):
    """Salva múltiplos clientes vindos do Excel de uma vez.
       clientes_dados é uma lista de tuplas correspondentes aos parâmetros."""
    conn = connect()
    cursor = conn.cursor()
    
    # Verifica se os dados incluem lote_id (terá 18 parâmetros em vez de 17)
    tem_lote = len(clientes_dados) > 0 and len(clientes_dados[0]) == 18
    
    if tem_lote:
        query = """
            INSERT INTO clientes (
                nome, cpf, telefone1, telefone2, telefone3, telefone4, 
                margem, whatsapp, sexo, idade, rua, bairro, cep, cidade, estado, 
                banco_id, banco_nome, lote_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pendente')
        """
    else:
        query = """
            INSERT INTO clientes (
                nome, cpf, telefone1, telefone2, telefone3, telefone4, 
                margem, whatsapp, sexo, idade, rua, bairro, cep, cidade, estado, 
                banco_id, banco_nome, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pendente')
        """
        
    try:
        cursor.executemany(query, clientes_dados)
        conn.commit()
        linhas_inseridas = cursor.rowcount
    except Exception as e:
        print("Erro ao inserir em lote:", e)
        conn.rollback()
        raise e
    finally:
        conn.close()
    return linhas_inseridas

def registrar_lote_importado(nome_arquivo, banco_id, banco_nome, quantidade_leads, importado_por, arquivo_bytes=None):
    """Registra um lote importado. O arquivo Excel é armazenado como BLOB no banco."""
    conn = connect()
    cursor = conn.cursor()
    
    blob_param = arquivo_bytes  # sqlite3 aceita bytes diretamente
    
    cursor.execute("""
    INSERT INTO lotes_importados (nome_arquivo, banco_id, banco_nome, quantidade_leads, importado_por, arquivo_blob)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (nome_arquivo, banco_id, banco_nome, quantidade_leads, importado_por, blob_param))
    conn.commit()
    novo_id = cursor.lastrowid if hasattr(cursor, 'lastrowid') and cursor.lastrowid else None
    
    if IS_POSTGRES and not novo_id:
        try:
            cursor.execute("SELECT MAX(id) FROM lotes_importados")
            novo_id = cursor.fetchone()[0]
        except:
            pass
        
    conn.close()
    return novo_id

def listar_lotes_importados():
    """Lista lotes importados SEM o blob binário (para listagem leve)."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, nome_arquivo, banco_id, banco_nome, quantidade_leads, 
               importado_por, criado_em
        FROM lotes_importados ORDER BY criado_em DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    result = []
    for r in rows:
        criado_em = r[6]
        if criado_em and hasattr(criado_em, 'isoformat'):
            criado_em = criado_em.isoformat()
        elif criado_em and isinstance(criado_em, str):
            criado_em = criado_em.replace(' ', 'T')
            
        if criado_em and not criado_em.endswith('Z') and '+' not in criado_em:
            criado_em += 'Z'
            
        result.append({
            'id': r[0],
            'nome_arquivo': r[1],
            'banco_id': r[2],
            'banco_nome': r[3],
            'quantidade_leads': r[4],
            'importado_por': r[5],
            'criado_em': criado_em
        })
    return result

def obter_lote_por_id(lote_id, incluir_blob=False):
    """Retorna dados de um lote. Se incluir_blob=True, inclui o arquivo binário."""
    conn = connect()
    cursor = conn.cursor()
    if incluir_blob:
        cursor.execute("SELECT id, nome_arquivo, banco_id, banco_nome, quantidade_leads, importado_por, criado_em, arquivo_blob FROM lotes_importados WHERE id = ?", (lote_id,))
    else:
        cursor.execute("SELECT id, nome_arquivo, banco_id, banco_nome, quantidade_leads, importado_por, criado_em FROM lotes_importados WHERE id = ?", (lote_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    result = {
        'id': row[0],
        'nome_arquivo': row[1],
        'banco_id': row[2],
        'banco_nome': row[3],
        'quantidade_leads': row[4],
        'importado_por': row[5],
        'criado_em': row[6]
    }
    if incluir_blob and len(row) > 7:
        blob = row[7]
        # No PostgreSQL com psycopg2, BYTEA vem como memoryview — converter para bytes
        if blob is not None and not isinstance(blob, bytes):
            blob = bytes(blob)
        result['arquivo_blob'] = blob
    return result

def excluir_lote_e_clientes(lote_id):
    conn = connect()
    cursor = conn.cursor()
    
    # Apaga todos os clientes daquele lote
    cursor.execute("DELETE FROM clientes WHERE lote_id = ?", (lote_id,))
    clientes_apagados = cursor.rowcount
    
    # Apaga o registro do lote
    cursor.execute("DELETE FROM lotes_importados WHERE id = ?", (lote_id,))
    conn.commit()
    conn.close()
    return clientes_apagados

def obter_stats_tela_vendedor(vendedor_id):
    """Retorna estatísticas para o header da Tela do Vendedor."""
    conn = connect()
    cursor = conn.cursor()
    
    # Pendentes (atribuídos e não tabulados)
    cursor.execute("SELECT COUNT(*) FROM clientes WHERE vendedor_id=? AND status='atribuido'", (vendedor_id,))
    pendentes = cursor.fetchone()[0]
    
    # Atribuídos (Total pendente) -> para o "1 de X"
    total_atribuidos = pendentes
    
    # Leads Trabalhados (Tabulados: elegível ou não elegível)
    cursor.execute("SELECT COUNT(*) FROM clientes WHERE vendedor_id=? AND status != 'pendente' AND status != 'atribuido'", (vendedor_id,))
    leads_atendidos = cursor.fetchone()[0]
    
    # Elegíveis
    cursor.execute("SELECT COUNT(*) FROM clientes WHERE vendedor_id=? AND LOWER(status) LIKE '%elegível%' AND LOWER(status) NOT LIKE '%não%'", (vendedor_id,))
    elegiveis = cursor.fetchone()[0]
    
    # Conversão
    taxa_conversao = 0
    if leads_atendidos > 0:
        taxa_conversao = (elegiveis / leads_atendidos) * 100
        
    # Valor total da margem dos elegíveis (prioriza margem_verificada)
    cursor.execute("SELECT SUM(COALESCE(margem_verificada, margem)) FROM clientes WHERE vendedor_id=? AND LOWER(status) LIKE '%elegível%' AND LOWER(status) NOT LIKE '%não%'", (vendedor_id,))
    valor_total = cursor.fetchone()[0] or 0.0
    
    conn.close()
    
    return {
        'pendentes': pendentes,
        'leads_atendidos': leads_atendidos,
        'elegiveis': elegiveis,
        'taxa_conversao': round(taxa_conversao, 1),
        'valor_total': valor_total,
        'total_atribuidos': total_atribuidos
    }

def obter_proximo_cliente_vendedor(vendedor_id):
    """Retorna o próximo cliente 'atribuido' para ser trabalhado pelo vendedor."""
    conn = connect()
    conn.row_factory = Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clientes WHERE vendedor_id=? AND status='atribuido' ORDER BY atribuido_em ASC LIMIT 1", (vendedor_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def obter_cliente_por_id(cliente_id, vendedor_id):
    """Retorna um cliente específico (para a função de Editar no histórico)."""
    conn = connect()
    conn.row_factory = Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clientes WHERE id=? AND vendedor_id=?", (cliente_id, vendedor_id))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def salvar_tabulacao_cliente(cliente_id, vendedor_id, status, bancos_elegiveis, margem_verificada, observacao):
    """Salva a tabulação feita pelo vendedor."""
    conn = connect()
    cursor = conn.cursor()
    
    # Verifica se o cliente pertence ao vendedor
    cursor.execute("SELECT id FROM clientes WHERE id=? AND vendedor_id=?", (cliente_id, vendedor_id))
    if not cursor.fetchone():
        conn.close()
        return False
        
    if IS_POSTGRES:
        data_tabulacao = "NOW() - INTERVAL '3 hours'"
    else:
        data_tabulacao = "datetime('now', '-3 hours')"

    cursor.execute(f'''
        UPDATE clientes 
        SET status=?, bancos_elegiveis=?, margem_verificada=?, margem=?, observacao=?, data_tabulacao={data_tabulacao}
        WHERE id=?
    ''', (status, bancos_elegiveis, margem_verificada, margem_verificada, observacao, cliente_id))
    
    conn.commit()
    conn.close()
    return True

def editar_cliente_vendedor(cliente_id, vendedor_id, dados):
    """Atualiza as informações de um cliente pelo vendedor."""
    conn = connect()
    cursor = conn.cursor()
    
    # Verifica permissão
    cursor.execute("SELECT id FROM clientes WHERE id=? AND vendedor_id=?", (cliente_id, vendedor_id))
    if not cursor.fetchone():
        conn.close()
        return False
        
    set_fields = []
    params = []
    
    # Campos que podem ser editados
    campos_permitidos = ['nome', 'cpf', 'telefone1', 'bancos_elegiveis', 'margem_verificada', 'status']
    for campo in campos_permitidos:
        if campo in dados:
            set_fields.append(f"{campo}=?")
            params.append(dados[campo])
            if campo == 'margem_verificada':
                set_fields.append("margem=?")
                params.append(dados[campo])
            
    if not set_fields:
        conn.close()
        return True
        
    params.append(cliente_id)
    
    query = f"UPDATE clientes SET {', '.join(set_fields)} WHERE id=?"
    cursor.execute(query, tuple(params))
    
    conn.commit()
    conn.close()
    return True

def obter_ultimos_clientes_trabalhados(vendedor_id, limite=5):
    """Retorna os últimos N clientes tabulados pelo vendedor."""
    conn = connect()
    conn.row_factory = Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM clientes 
        WHERE vendedor_id=? AND status != 'pendente' AND status != 'atribuido' 
        ORDER BY data_tabulacao DESC 
        LIMIT ?
    ''', (vendedor_id, limite))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_distribuicao_por_vendedor():
    """Retorna cada vendedor ativo com total atribuído e últimos 3 clientes."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, COALESCE(NULLIF(u.nome, ''), u.username) as nome_final,
               COUNT(c.id) as total_atribuidos
        FROM usuarios u
        LEFT JOIN clientes c ON c.vendedor_id = u.id AND c.status = 'atribuido'
        WHERE u.papel = 'vendedor' AND u.ativo = ?
        GROUP BY u.id, nome_final
        ORDER BY total_atribuidos DESC, nome_final
    """, (True,))
    rows = cursor.fetchall()
    result = []
    for r in rows:
        vid, vnome, vtotal = r
        cursor.execute("""
            SELECT nome, cpf, telefone1
            FROM clientes
            WHERE vendedor_id = ? AND status = 'atribuido'
            ORDER BY atribuido_em DESC LIMIT 3
        """, (vid,))
        ultimos = [{'nome': u[0], 'cpf': u[1] or '', 'telefone': u[2] or ''} for u in cursor.fetchall()]
        result.append({
            'id': vid,
            'nome': vnome,
            'total_atribuidos': vtotal,
            'ultimos_clientes': ultimos
        })
    conn.close()
    return result

def obter_desempenho_vendedores(data_inicio=None, data_fim=None):
    """Retorna estatísticas de performance real baseada nas tabulações dos vendedores."""
    conn = connect()
    cursor = conn.cursor()
    
    # Busca todos os usuários vendedores ativos ou que tenham leads
    cursor.execute("SELECT id, nome, username, ativo FROM usuarios WHERE papel='vendedor'")
    vendedores = cursor.fetchall()
    
    result = []
    for vid, nome, uname, ativo in vendedores:
        nome_final = nome or uname.split('@')[0].replace('.', ' ').title()
        
        # Filtro base: Clientes que já foram trabalhados por este vendedor
        # Não contamos 'pendente' ou 'atribuido' no desempenho de consultas realizadas
        where_base = " WHERE vendedor_id = ? AND status NOT IN ('pendente', 'atribuido')"
        params = [vid]
        
        if data_inicio:
            where_base += " AND data_tabulacao >= ?"
            params.append(f"{data_inicio} 00:00:00")
        if data_fim:
            where_base += " AND data_tabulacao <= ?"
            params.append(f"{data_fim} 23:59:59")
            
        # Elegíveis: Status que indicam sucesso ou interesse
        # Qualquer coisa que contenha 'elegível' e não contenha 'não'
        where_elegivel = where_base + " AND (LOWER(status) LIKE '%elegível%' AND LOWER(status) NOT LIKE '%não%')"
        cursor.execute(f"SELECT COUNT(*) FROM clientes {where_elegivel}", tuple(params))
        elegiveis = cursor.fetchone()[0]
        
        # Não Elegíveis: Tudo que foi trabalhado mas não é elegível
        where_nao = where_base + " AND (LOWER(status) LIKE '%não elegível%' OR LOWER(status) LIKE '%rejeitado%' OR LOWER(status) LIKE '%sem interesse%' OR LOWER(status) LIKE '%ocupado%')"
        cursor.execute(f"SELECT COUNT(*) FROM clientes {where_nao}", tuple(params))
        nao_elegiveis = cursor.fetchone()[0]
        
        # Total de Consultas Reais = Soma do que foi trabalhado
        total_trabalhado = elegiveis + nao_elegiveis
        
        taxa = 0
        if total_trabalhado > 0:
            taxa = round((elegiveis / total_trabalhado) * 100, 1)
            
        result.append({
            'nome': nome_final,
            'status': 'Ativo' if ativo else 'Inativo',
            'total_consultas': total_trabalhado,
            'elegiveis': elegiveis,
            'nao_elegiveis': nao_elegiveis,
            'taxa_conversao': taxa
        })
    
    # Ordena por quem mais trabalhou
    result.sort(key=lambda x: x['total_consultas'], reverse=True)
    
    conn.close()
    return result

def obter_performance_ranking_vendedores(data_inicio=None, data_fim=None):
    """Retorna estatísticas detalhadas para o Ranking de Performance."""
    conn = connect()
    cursor = conn.cursor()
    
    # Busca vendedores
    cursor.execute("SELECT id, nome, username FROM usuarios WHERE papel='vendedor'")
    vendedores = cursor.fetchall()
    
    result = []
    for vid, nome, uname in vendedores:
        nome_final = nome or uname.split('@')[0].replace('.', ' ').title()
        
        where_base = " WHERE vendedor_id = ?"
        params = [vid]
        if data_inicio:
            where_base += " AND importado_em >= ?"
            params.append(f"{data_inicio} 00:00:00")
        if data_fim:
            where_base += " AND importado_em <= ?"
            params.append(f"{data_fim} 23:59:59")

        # 1. Atribuídos (Total)
        cursor.execute(f"SELECT COUNT(*) FROM clientes {where_base}", tuple(params))
        atribuidos = cursor.fetchone()[0]

        # 2. Elegíveis
        where_eleg = where_base + " AND LOWER(status) LIKE '%elegível%' AND LOWER(status) NOT LIKE '%não%'"
        cursor.execute(f"SELECT COUNT(*) FROM clientes {where_eleg}", tuple(params))
        elegiveis = cursor.fetchone()[0]

        # 3. Não Elegíveis (Rejeitados/Não elegíveis)
        where_nao = where_base + " AND (LOWER(status) LIKE '%não elegível%' OR LOWER(status) LIKE '%rejeitado%')"
        cursor.execute(f"SELECT COUNT(*) FROM clientes {where_nao}", tuple(params))
        nao_elegiveis = cursor.fetchone()[0]

        # 4. Trabalhados (Elegíveis + Não Elegíveis)
        trabalhados = elegiveis + nao_elegiveis

        # 5. Pendentes
        pendentes = atribuidos - trabalhados

        # 6. Conversão
        taxa_conv = round((elegiveis / trabalhados * 100), 1) if trabalhados > 0 else 0

        # 7. Margem Total (Soma da margem dos elegíveis - prioriza margem verificada)
        cursor.execute(f"SELECT SUM(COALESCE(margem_verificada, margem)) FROM clientes {where_eleg}", tuple(params))
        margem_total = cursor.fetchone()[0] or 0

        # 8. Bancos Mais Utilizados (Top 2)
        cursor.execute(f"""
            SELECT banco_nome, COUNT(*) as qtd 
            FROM clientes {where_base} AND banco_nome IS NOT NULL AND banco_nome != ''
            GROUP BY banco_nome ORDER BY qtd DESC LIMIT 2
        """, tuple(params))
        bancos = [{"nome": b[0], "qtd": b[1]} for b in cursor.fetchall()]

        result.append({
            'nome': nome_final,
            'atribuidos': atribuidos,
            'trabalhados': trabalhados,
            'elegiveis': elegiveis,
            'pendentes': pendentes,
            'conversao': taxa_conv,
            'margem_total': margem_total,
            'bancos': bancos,
            'taxa_trabalho': round((trabalhados / atribuidos * 100), 1) if atribuidos > 0 else 0
        })

    # Ordena pelo volume de margem (Ranking)
    result.sort(key=lambda x: x['margem_total'], reverse=True)
    
    conn.close()
    return result

def listar_consultas_admin(data_inicio=None, data_fim=None, busca=None):
    """Retorna o histórico completo de consultas para o painel administrativo."""
    conn = connect()
    cursor = conn.cursor()
    
    where_clauses = ["status NOT IN ('pendente', 'atribuido')"]
    params = []
    
    if data_inicio:
        where_clauses.append("data_tabulacao >= ?")
        params.append(f"{data_inicio} 00:00:00")
    if data_fim:
        where_clauses.append("data_tabulacao <= ?")
        params.append(f"{data_fim} 23:59:59")
    
    if busca:
        busca_val = f"%{busca}%"
        where_clauses.append("(nome LIKE ? OR cpf LIKE ? OR vendedor_nome LIKE ? OR banco_nome LIKE ?)")
        params.extend([busca_val, busca_val, busca_val, busca_val])
    
    query = f"""
        SELECT data_tabulacao, vendedor_nome, nome, cpf, banco_nome, margem_verificada, status
        FROM clientes
        WHERE {" AND ".join(where_clauses)}
        ORDER BY data_tabulacao DESC
        LIMIT 500
    """
    
    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    from datetime import datetime
    for r in rows:
        data_fmt = ""
        if r[0]:
            try:
                if hasattr(r[0], 'strftime'):
                    # PostgreSQL retorna datetime object diretamente
                    data_fmt = r[0].strftime('%d/%m/%Y %H:%M')
                else:
                    dt = datetime.fromisoformat(str(r[0]).replace(' ', 'T'))
                    data_fmt = dt.strftime('%d/%m/%Y %H:%M')
            except:
                data_fmt = str(r[0])
        
        result.append({
            'data_hora': data_fmt,
            'vendedor': r[1] or 'Sistema',
            'cliente': r[2],
            'cpf': r[3] or '--',
            'banco': r[4] or '--',
            'margem': r[5] or 0.0,
            'status': r[6] or 'pendente'
        })
    return result

# ── Gerenciamento de Usuários ──

def listar_usuarios():
    """Lista todos os usuários com seus dados completos."""
    conn = connect()
    cursor = conn.cursor()
    
    fmt_data = "COALESCE(TO_CHAR(criado_em, 'DD/MM/YYYY'), 'Sem data')" if IS_POSTGRES else "COALESCE(strftime('%d/%m/%Y', criado_em), 'Sem data')"
    
    cursor.execute(f"""
    SELECT id, username, nome, email, papel, localizacao, ativo,
           {fmt_data} as criado_fmt, foto,
           lat, lng, ip
    FROM usuarios ORDER BY papel DESC, nome
    """)
    rows = cursor.fetchall()
    conn.close()
    return [{
    'id': r[0], 
    'username': r[1],
    'nome_exibicao': r[2] or r[1].split('@')[0].replace('.', ' ').title(),
    'nome': r[2] or '',
    'email': r[3] or '',
    'papel': r[4] or 'vendedor',
    'localizacao': r[5] or '',
    'ativo': r[6],
    'criado_em': r[7] or '--',
    'foto': r[8] or '',
    'lat': r[9],
    'lng': r[10],
    'ip': r[11]
    } for r in rows]

def atualizar_foto_usuario(username, foto_base64):
    """Atualiza a foto de perfil do usuário."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE usuarios SET foto = ? WHERE username = ?", (foto_base64, username))
    conn.commit()
    conn.close()

def adicionar_usuario(username, password, nome='', email='', papel='vendedor'):
    """Adiciona um novo usuário."""
    conn = connect()
    cursor = conn.cursor()
    email_db = email if email and email.strip() else None
    cursor.execute(
        "INSERT INTO usuarios (username, password, nome, email, papel, ativo, criado_em) VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP)",
        (username, password, nome, email_db, papel, True)
    )
    conn.commit()
    novo_id = cursor.lastrowid
    conn.close()
    return novo_id

def desativar_usuario(usuario_id):
    """Ativa ou desativa um usuário."""
    conn = connect()
    cursor = conn.cursor()
    try:
        # Pega status atual
        cursor.execute("SELECT ativo FROM usuarios WHERE id = ?", (usuario_id,))
        row = cursor.fetchone()
        if row:
            # Inverte o status usando booleano python
            # Aceita 1, True, 't', 'true' como ativo. Se for 0, False, None, 'f', etc, é inativo.
            status_atual = row[0]
            esta_ativo = status_atual in (1, True, 't', 'true')
            novo_status = False if esta_ativo else True
            
            cursor.execute("UPDATE usuarios SET ativo = ? WHERE id = ?", (novo_status, usuario_id))
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def deletar_usuario(usuario_id):
    """Remove permanentemente um usuário (não-admin)."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM usuarios WHERE id=? AND papel != 'admin'", (usuario_id,))
    conn.commit()
    conn.close()

def editar_usuario(usuario_id, username, password, nome, email, papel):
    """Atualiza os dados de um usuário."""
    conn = connect()
    cursor = conn.cursor()
    email_db = email if email and email.strip() else None
    if password:
        cursor.execute(
            "UPDATE usuarios SET username=?, password=?, nome=?, email=?, papel=? WHERE id=?",
            (username, password, nome, email_db, papel, usuario_id)
        )
    else:
        cursor.execute(
            "UPDATE usuarios SET username=?, nome=?, email=?, papel=? WHERE id=?",
            (username, nome, email_db, papel, usuario_id)
        )
    conn.commit()
    conn.close()

def atualizar_localizacao_usuario(username, localizacao, lat=None, lng=None, ip=None):
    """Salva a localização, coordenadas e IP do usuário no login."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE usuarios SET localizacao = ?, lat = ?, lng = ?, ip = ? WHERE username = ?", 
                   (localizacao, lat, lng, ip, username))
    conn.commit()
    conn.close()

def listar_clientes():
    """Retorna todos os clientes cadastrados."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, nome, cpf, telefone1, banco_id, banco_nome, margem,
               status, vendedor_id, vendedor_nome
        FROM clientes ORDER BY importado_em DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [{
        'id': r[0], 'nome': r[1], 'cpf': r[2], 'telefone1': r[3],
        'banco_id': r[4], 'banco_nome': r[5], 'margem': r[6],
        'status': r[7], 'vendedor_id': r[8], 'vendedor_nome': r[9]
    } for r in rows]

# ── Chat da Equipe ──

def salvar_mensagem_chat(remetente, nome_exibicao, mensagem, destinatario='geral'):
    """Salva uma mensagem no chat (geral ou privado)."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO mensagens_chat (remetente, nome_exibicao, destinatario, mensagem) VALUES (?,?,?,?)",
        (remetente, nome_exibicao, destinatario, mensagem)
    )
    conn.commit()
    novo_id = cursor.lastrowid
    conn.close()
    return novo_id

def buscar_mensagens_chat(usuario1, usuario2='geral', limite=100):
    """Retorna o histórico de chat entre dois usuários, ou do canal geral."""
    conn = connect()
    cursor = conn.cursor()
    
    fmt_hora = "TO_CHAR(enviado_em, 'HH24:MI')" if IS_POSTGRES else "strftime('%H:%M', enviado_em)"
    fmt_data = "TO_CHAR(enviado_em, 'DD/MM/YYYY')" if IS_POSTGRES else "strftime('%d/%m/%Y', enviado_em)"
    
    if usuario2 == 'geral':
        cursor.execute(f"""
            SELECT id, remetente, nome_exibicao, destinatario, mensagem,
                   {fmt_hora} as hora,
                   {fmt_data} as data,
                   enviado_em
            FROM mensagens_chat
            WHERE destinatario = 'geral'
            ORDER BY enviado_em DESC LIMIT ?
        """, (limite,))
    elif usuario2.startswith('canal_'):
        cursor.execute(f"""
            SELECT id, remetente, nome_exibicao, destinatario, mensagem,
                   {fmt_hora} as hora,
                   {fmt_data} as data,
                   enviado_em
            FROM mensagens_chat
            WHERE destinatario = ?
            ORDER BY enviado_em DESC LIMIT ?
        """, (usuario2, limite))
    else:
        cursor.execute(f"""
            SELECT id, remetente, nome_exibicao, destinatario, mensagem,
                   {fmt_hora} as hora,
                   {fmt_data} as data,
                   enviado_em
            FROM mensagens_chat
            WHERE (remetente = ? AND destinatario = ?) OR (remetente = ? AND destinatario = ?)
            ORDER BY enviado_em DESC LIMIT ?
        """, (usuario1, usuario2, usuario2, usuario1, limite))
    
    rows = cursor.fetchall()
    conn.close()
    msgs = [{
    'id': r[0], 'remetente': r[1], 'nome': r[2], 'destinatario': r[3],
    'mensagem': r[4], 'hora': r[5], 'data': r[6]
    } for r in reversed(rows)]
    return msgs

def get_admin_stats(data_inicio=None, data_fim=None):
    """Retorna estatísticas globais reais para o dashboard administrativo."""
    conn = connect()
    cursor = conn.cursor()
    
    # Filtro de data (opcional)
    where_clause = " WHERE 1=1"
    params = []
    if data_inicio:
        where_clause += " AND importado_em >= ?"
        params.append(f"{data_inicio} 00:00:00")
    if data_fim:
        where_clause += " AND importado_em <= ?"
        params.append(f"{data_fim} 23:59:59")
        
    # 1. Total de Clientes
    cursor.execute(f"SELECT COUNT(*) FROM clientes{where_clause}", tuple(params))
    total_clientes = cursor.fetchone()[0]
    
    # 2. Pendentes (Aguardando distribuição) - Leads sem vendedor_id
    cursor.execute(f"SELECT COUNT(*) FROM clientes{where_clause} AND vendedor_id IS NULL", tuple(params))
    pendentes = cursor.fetchone()[0]
    
    # 3. Atribuídos (Já em posse de algum vendedor) - Leads com vendedor_id
    cursor.execute(f"SELECT COUNT(*) FROM clientes{where_clause} AND vendedor_id IS NOT NULL", tuple(params))
    atribuidos = cursor.fetchone()[0]
    
    # 4. Vendedores Ativos
    cursor.execute("SELECT COUNT(*) FROM usuarios WHERE papel='vendedor' AND ativo=?", (True,))
    vendedores_ativos = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        'total_clientes': total_clientes,
        'pendentes': pendentes,
        'atribuidos': atribuidos,
        'vendedores_ativos': vendedores_ativos
    }

def get_analytics_dashboard(data_inicio=None, data_fim=None):
    """Retorna dados agregados para os gráficos da aba de Análises."""
    conn = connect()
    cursor = conn.cursor()
    
    where_clause = " WHERE 1=1"
    params = []
    if data_inicio:
        where_clause += " AND importado_em >= ?"
        params.append(f"{data_inicio} 00:00:00")
    if data_fim:
        where_clause += " AND importado_em <= ?"
        params.append(f"{data_fim} 23:59:59")
        
    where_tab = " WHERE data_tabulacao IS NOT NULL"
    params_tab = []
    if data_inicio:
        where_tab += " AND data_tabulacao >= ?"
        params_tab.append(f"{data_inicio} 00:00:00")
    else:
        if IS_POSTGRES:
            where_tab += " AND data_tabulacao >= NOW() - INTERVAL '7 days'"
        else:
            where_tab += " AND data_tabulacao >= date('now', '-7 days')"
    if data_fim:
        where_tab += " AND data_tabulacao <= ?"
        params_tab.append(f"{data_fim} 23:59:59")

    # 1. Leads por Status
    cursor.execute(f"SELECT status, COUNT(*) FROM clientes {where_clause} GROUP BY status", tuple(params))
    status_raw = cursor.fetchall()
    leads_status = {'labels': [], 'data': []}
    for s, c in status_raw:
        st = s.capitalize() if s else 'Desconhecido'
        leads_status['labels'].append(st)
        leads_status['data'].append(c)

    # 2. Top Bancos
    cursor.execute(f"SELECT banco_nome, COUNT(*) FROM clientes {where_clause} AND banco_nome IS NOT NULL AND banco_nome != '' GROUP BY banco_nome ORDER BY COUNT(*) DESC LIMIT 5", tuple(params))
    bancos_raw = cursor.fetchall()
    leads_banco = {'labels': [], 'data': []}
    for b, c in bancos_raw:
        leads_banco['labels'].append(b)
        leads_banco['data'].append(c)

    # 3. Evolução de Tabulações (Line Chart)
    cursor.execute(f"SELECT DATE(data_tabulacao), COUNT(*) FROM clientes {where_tab} GROUP BY DATE(data_tabulacao) ORDER BY DATE(data_tabulacao)", tuple(params_tab))
    evolucao_raw = cursor.fetchall()
    evolucao_diaria = {'labels': [], 'data': []}
    for d, c in evolucao_raw:
        try:
            # No PostgreSQL, DATE() retorna um objeto datetime.date
            if not isinstance(d, str):
                d = d.isoformat()
            # Formata data para DD/MM
            parts = d.split('-')
            lbl = f"{parts[2]}/{parts[1]}"
        except:
            lbl = str(d)
        evolucao_diaria['labels'].append(lbl)
        evolucao_diaria['data'].append(c)

    # 4. Produtividade Vendedores
    cursor.execute(f"SELECT vendedor_nome, COUNT(*) FROM clientes {where_clause} AND vendedor_nome IS NOT NULL AND status NOT IN ('pendente', 'atribuido') GROUP BY vendedor_nome ORDER BY COUNT(*) DESC LIMIT 5", tuple(params))
    prod_raw = cursor.fetchall()
    prod_vendedores = {'labels': [], 'data': []}
    for v, c in prod_raw:
        prod_vendedores['labels'].append(v.split()[0].title()) # Primeiro nome
        prod_vendedores['data'].append(c)

    conn.close()
    
    return {
        'leads_status': leads_status,
        'leads_banco': leads_banco,
        'evolucao_diaria': evolucao_diaria,
        'prod_vendedores': prod_vendedores
    }

def listar_scripts(apenas_publicados=False):
    """Lista todos os scripts do banco de dados, priorizando fixados."""
    conn = connect()
    cursor = conn.cursor()
    
    fmt_data = "TO_CHAR(atualizado_em, 'DD/MM/YYYY HH24:MI')" if IS_POSTGRES else "strftime('%d/%m/%Y %H:%M', atualizado_em)"
    
    query = f"SELECT id, titulo, categoria, conteudo, publicado, {fmt_data}, fixado FROM scripts"
    if apenas_publicados:
        query += " WHERE publicado = 1"
    query += " ORDER BY fixado DESC, categoria ASC, atualizado_em DESC"
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()
    return [{
    'id': r[0], 'titulo': r[1], 'categoria': r[2], 
    'conteudo': r[3], 'publicado': bool(r[4]), 'data': r[5],
    'fixado': bool(r[6])
    } for r in rows]

def adicionar_script(titulo, categoria, conteudo):
    """Cria um novo script (como rascunho por padrão)."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO scripts (titulo, categoria, conteudo, publicado) VALUES (?, ?, ?, ?)",
                   (titulo, categoria, conteudo, False))
    conn.commit()
    conn.close()

def editar_script(id, titulo, categoria, conteudo):
    """Atualiza um script existente."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE scripts SET titulo=?, categoria=?, conteudo=?, atualizado_em=CURRENT_TIMESTAMP WHERE id=?",
                   (titulo, categoria, conteudo, id))
    conn.commit()
    conn.close()

def deletar_script(id):
    """Remove um script permanentemente."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM scripts WHERE id=?", (id,))
    conn.commit()
    conn.close()

def alternar_publicacao_script(id):
    """Inverte o status de publicação do script."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT publicado FROM scripts WHERE id = ?", (id,))
    row = cursor.fetchone()
    if row:
        novo_status = False if row[0] in (1, True, 't', 'true') else True
        cursor.execute("UPDATE scripts SET publicado = ?, atualizado_em=CURRENT_TIMESTAMP WHERE id=?", (novo_status, id))
        conn.commit()
    conn.close()

def alternar_fixar_script(id):
    """Inverte o status de fixado do script."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT fixado FROM scripts WHERE id = ?", (id,))
    row = cursor.fetchone()
    if row:
        novo_status = False if row[0] in (1, True, 't', 'true') else True
        cursor.execute("UPDATE scripts SET fixado = ? WHERE id=?", (novo_status, id))
        conn.commit()
    conn.close()

def salvar_log(usuario, acao, detalhe=None, ip=None, localizacao=None):
    """Registra uma ação ou acesso no sistema."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO logs (usuario, acao, detalhe, ip, localizacao) VALUES (?, ?, ?, ?, ?)",
        (usuario, acao, detalhe, ip, localizacao)
    )
    conn.commit()
    conn.close()

def buscar_logs(limit=50, offset=0, data_inicio=None, data_fim=None, usuario_filtro=None, acao_filtro=None):
    """Retorna os logs paginados com filtros opcionais e total de registros."""
    conn = connect()
    cursor = conn.cursor()
    
    base_query = "FROM logs WHERE 1=1"
    params = []
    
    if data_inicio:
        if IS_POSTGRES:
            base_query += " AND (criado_em - INTERVAL '3 hours') >= ?"
        else:
            base_query += " AND datetime(criado_em, '-3 hours') >= ?"
        params.append(f"{data_inicio} 00:00:00")
    if data_fim:
        if IS_POSTGRES:
            base_query += " AND (criado_em - INTERVAL '3 hours') <= ?"
        else:
            base_query += " AND datetime(criado_em, '-3 hours') <= ?"
        params.append(f"{data_fim} 23:59:59")
    if usuario_filtro:
        base_query += " AND usuario LIKE ?"
        params.append(f"%{usuario_filtro}%")
    if acao_filtro:
        base_query += " AND acao LIKE ?"
        params.append(f"%{acao_filtro}%")
    
    # Primeiro conta o total para a paginação
    cursor.execute(f"SELECT COUNT(*) {base_query}", tuple(params))
    total = cursor.fetchone()[0]
    
    # Depois busca os dados da página
    if IS_POSTGRES:
        fmt_data = "TO_CHAR(criado_em - INTERVAL '3 hours', 'DD/MM/YYYY HH24:MI')"
    else:
        fmt_data = "strftime('%d/%m/%Y %H:%M', criado_em, '-3 hours')"
    query = f"""
    SELECT usuario, acao, detalhe, ip, localizacao, 
           {fmt_data} as data_fmt
    {base_query}
    ORDER BY criado_em DESC LIMIT ? OFFSET ?
    """
    
    params.extend([limit, offset])
    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    conn.close()
    
    return {
    'total': total,
    'logs': [{
        'usuario': r[0], 'acao': r[1], 'detalhe': r[2],
        'ip': r[3], 'localizacao': r[4], 'data': r[5]
    } for r in rows]
    }

def salvar_canal(canal_id, nome, privacidade, criado_por, membros):
    """Salva ou atualiza um canal e seus membros."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO canais (id, nome, privacidade, criado_por) VALUES (?,?,?,?)",
                   (canal_id, nome, privacidade, criado_por))
    
    # Atualiza membros: remove antigos e insere novos
    cursor.execute("DELETE FROM membros_canal WHERE canal_id = ?", (canal_id,))
    for m in membros:
        cursor.execute("INSERT INTO membros_canal (canal_id, usuario_username) VALUES (?,?)", (canal_id, m))
    
    conn.commit()
    conn.close()

def listar_canais(usuario_username=None):
    """Lista os canais aos quais o usuário tem acesso (ou todos se admin)."""
    conn = connect()
    cursor = conn.cursor()
    
    # Se for admin, vê todos os canais. Caso contrário, apenas públicos ou onde é membro.
    if usuario_username and 'admin' not in usuario_username.lower():
        cursor.execute("""
            SELECT DISTINCT c.id, c.nome, c.privacidade, c.criado_por
            FROM canais c
            LEFT JOIN membros_canal m ON m.canal_id = c.id
            WHERE c.privacidade = 'publico' OR m.usuario_username = ?
        """, (usuario_username,))
    else:
        cursor.execute("SELECT id, nome, privacidade, criado_por FROM canais")
    
    rows = cursor.fetchall()
    canais = []
    for r in rows:
        cid = r[0]
        cursor.execute("SELECT usuario_username FROM membros_canal WHERE canal_id = ?", (cid,))
        membros = [m[0] for m in cursor.fetchall()]
        canais.append({
            'id': cid,
            'nome': r[1],
            'privacidade': r[2],
            'criado_por': r[3],
            'membros': membros
        })
    
    conn.close()
    return canais

def buscar_membros_canal(canal_id):
    """Retorna a lista de usernames dos membros de um canal."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT usuario_username FROM membros_canal WHERE canal_id = ?", (canal_id,))
    membros = [r[0] for r in cursor.fetchall()]
    conn.close()
    return membros

def remover_membro_canal(canal_id, username):
    """Remove um membro específico de um canal."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM membros_canal WHERE canal_id = ? AND usuario_username = ?", (canal_id, username))
    conn.commit()
    conn.close()

def deletar_canal(canal_id):
    """Remove permanentemente um canal e seus membros."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM membros_canal WHERE canal_id = ?", (canal_id,))
    cursor.execute("DELETE FROM canais WHERE id = ?", (canal_id,))
    cursor.execute("DELETE FROM mensagens_chat WHERE destinatario = ?", (canal_id,))
    conn.commit()
    conn.close()

def buscar_historico_monitor(alvo, limit=100, offset=0):
    """Busca o histórico completo de mensagens onde o alvo seja o rementente ou destinatário."""
    conn = connect()
    cursor = conn.cursor()
    
    fmt_hora = "TO_CHAR(enviado_em, 'HH24:MI')" if IS_POSTGRES else "strftime('%H:%M', enviado_em)"
    fmt_data = "TO_CHAR(enviado_em, 'DD/MM/YYYY')" if IS_POSTGRES else "strftime('%d/%m/%Y', enviado_em)"
    
    cursor.execute(f"""
    SELECT id, remetente, nome_exibicao, destinatario, mensagem,
           {fmt_hora} as hora,
           {fmt_data} as data
    FROM mensagens_chat
    WHERE remetente = ? OR destinatario = ?
    ORDER BY enviado_em DESC LIMIT ? OFFSET ?
    """, (alvo, alvo, limit, offset))
    rows = cursor.fetchall()
    conn.close()
    
    msgs = [{
    'id': r[0], 'remetente': r[1], 'nome': r[2], 'destinatario': r[3],
    'mensagem': r[4], 'hora': r[5], 'data': r[6]
    } for r in reversed(rows)]
    return msgs

def alternar_fixar_conversa(username, target_id):
    """Alterna o status de fixado de uma conversa para um usuário."""
    conn = connect()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM conversas_fixadas WHERE usuario_username = ? AND target_id = ?", (username, target_id))
        row = cursor.fetchone()
        if row:
            cursor.execute("DELETE FROM conversas_fixadas WHERE id = ?", (row[0],))
            fixado = False
        else:
            cursor.execute("INSERT INTO conversas_fixadas (usuario_username, target_id) VALUES (?, ?)", (username, target_id))
            fixado = True
        conn.commit()
        return {'success': True, 'fixado': fixado}
    except Exception as e:
        return {'success': False, 'error': str(e)}
    finally:
        conn.close()

def buscar_conversas_fixadas(username):
    """Retorna lista de target_ids fixados pelo usuário."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT target_id FROM conversas_fixadas WHERE usuario_username = ?", (username,))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

# ── Notificações do Chat (mensagens não lidas) ──

def contar_mensagens_chat_nao_lidas(username):
    """Conta o total de mensagens não lidas no chat geral para o usuário."""
    conn = connect()
    cursor = conn.cursor()
    
    # Busca o timestamp da última leitura do canal geral
    cursor.execute(
        "SELECT lido_em FROM chat_ultima_leitura WHERE usuario_username = ? AND canal = 'geral'",
        (username,)
    )
    row = cursor.fetchone()
    
    if row:
        ultimo_lido = row[0]
        # Conta mensagens no canal geral após a última leitura, excluindo as do próprio usuário
        cursor.execute(
            "SELECT COUNT(*) FROM mensagens_chat WHERE destinatario = 'geral' AND remetente != ? AND enviado_em > ?",
            (username, ultimo_lido)
        )
    else:
        # Se nunca leu, conta todas as mensagens do canal geral (exceto as próprias)
        cursor.execute(
            "SELECT COUNT(*) FROM mensagens_chat WHERE destinatario = 'geral' AND remetente != ?",
            (username,)
        )
    
    count = cursor.fetchone()[0]
    conn.close()
    return count

def atualizar_ultima_leitura_chat(username, canal='geral'):
    """Atualiza o timestamp da última leitura do chat para o usuário."""
    conn = connect()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO chat_ultima_leitura (usuario_username, canal, lido_em)
        VALUES (?, ?, CURRENT_TIMESTAMP)
    """, (username, canal))
    
    conn.commit()
    conn.close()