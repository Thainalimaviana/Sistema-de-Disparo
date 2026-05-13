import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import math
from datetime import datetime
from flask_socketio import SocketIO, emit, join_room, leave_room
import urllib.request, json as _json
import pandas as pd
from db.db import (init_db, verificar_login, salvar_comunicado, buscar_comunicados,
                   editar_comunicado, deletar_comunicado, alternar_fixar_comunicado,
                   marcar_todos_lidos_usuario, arquivar_comunicado_usuario, desarquivar_comunicado_usuario,
                   listar_bancos, adicionar_banco, remover_banco,
                   criar_solicitacao_leads, listar_solicitacoes,
                   aprovar_solicitacao, rejeitar_solicitacao,
                   get_admin_stats, get_clientes_por_banco,
                   listar_vendedores, adicionar_vendedor, remover_vendedor,
                   distribuir_clientes, get_distribuicao_por_vendedor,
                   listar_usuarios, adicionar_usuario, desativar_usuario,
                   deletar_usuario, atualizar_localizacao_usuario,
                   salvar_mensagem_chat, buscar_mensagens_chat,
                    obter_atividades_recentes, obter_dashboard_stats, obter_ranking_bancos, marcar_lido_usuario,
                     obter_desempenho_vendedores, obter_performance_ranking_vendedores, listar_consultas_admin,
                     listar_scripts, adicionar_script, editar_script, deletar_script, alternar_publicacao_script, alternar_fixar_script,
                     salvar_canal, listar_canais, deletar_canal, remover_membro_canal, editar_usuario,
                    salvar_log, buscar_logs,
                    salvar_clientes_lote, obter_stats_tela_vendedor,
                    obter_proximo_cliente_vendedor, salvar_tabulacao_cliente,
                    obter_ultimos_clientes_trabalhados, obter_cliente_por_id, obter_configuracao, salvar_configuracao,
                    alternar_fixar_conversa, buscar_conversas_fixadas,
                    contar_mensagens_chat_nao_lidas, atualizar_ultima_leitura_chat)

app = Flask(__name__)
app.secret_key = 'uma_chave_secreta_muito_segura'
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

# Usuários online: {username: nome_exibicao}
usuarios_online = {}

ESTADOS_BR = {
    'Acre': 'AC', 'Alagoas': 'AL', 'Amapá': 'AP', 'Amazonas': 'AM', 'Bahia': 'BA',
    'Ceará': 'CE', 'Distrito Federal': 'DF', 'Espírito Santo': 'ES', 'Goiás': 'GO',
    'Maranhão': 'MA', 'Mato Grosso': 'MT', 'Mato Grosso do Sul': 'MS', 'Minas Gerais': 'MG',
    'Pará': 'PA', 'Paraíba': 'PB', 'Paraná': 'PR', 'Pernambuco': 'PE', 'Piauí': 'PI',
    'Rio de Janeiro': 'RJ', 'Rio Grande do Norte': 'RN', 'Rio Grande do Sul': 'RS',
    'Rondônia': 'RO', 'Roraima': 'RR', 'Santa Catarina': 'SC', 'São Paulo': 'SP',
    'Sergipe': 'SE', 'Tocantins': 'TO'
}

def get_client_ip():
    """Captura o IP real do usuário, tratando headers de proxy."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr

import traceback

try:
    init_db()
except Exception as e:
    print("\n" + "="*50)
    print("ERRO CRÍTICO AO INICIALIZAR O BANCO DE DADOS:")
    print("Isso geralmente impede a aplicação de rodar no Render.")
    traceback.print_exc()
    print("="*50 + "\n")

@app.route('/')
def login_page():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    location = data.get('location')

    try:
        user_data = verificar_login(username, password)
        if user_data:
            session['user'] = username
            session['role'] = user_data['papel']
            # session['user_foto'] = user_data.get('foto', '') # REMOVIDO: Causa erro de cookie muito grande (Header Line Too Long)
            
            # Pega o primeiro nome (trata se for e-mail ou nome completo)
            nome_real = user_data.get('nome')
            if not nome_real or nome_real.strip() == "":
                # Se não tem nome, pega a parte antes do @ do email
                nome_display = username.split('@')[0].split('.')[0].split('_')[0].capitalize()
            else:
                # Pega apenas o primeiro nome do campo nome completo
                nome_display = nome_real.split(' ')[0].capitalize()
                
            session['user_nome'] = nome_display
            session['show_welcome'] = True
            
            # Processamento de Localização e Logs
            ip_addr = get_client_ip()
            ua = request.headers.get('User-Agent', '').lower()
            dispositivo = "Celular" if any(x in ua for x in ['mobile', 'android', 'iphone', 'ipad']) else "Computador"
            
            loc_str = ""
            
            if location and location.get('lat') and location.get('lng'):
                lat, lng = location['lat'], location['lng']
                try:
                    geo_url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lng}"
                    req = urllib.request.Request(geo_url, headers={'User-Agent': 'ConsigTech/1.0'})
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        geo = _json.loads(resp.read())
                    
                    addr = geo.get('address', {})
                    rua = addr.get('road') or addr.get('pedestrian') or ''
                    numero = addr.get('house_number', '')
                    bairro = addr.get('suburb') or addr.get('neighbourhood') or ''
                    cidade = addr.get('city') or addr.get('town') or addr.get('municipality') or ''
                    estado_nome = addr.get('state', '')
                    uf = ESTADOS_BR.get(estado_nome, estado_nome)

                    partes = [f"[{dispositivo}]"]
                    if rua: partes.append(f"{rua}{', ' + numero if numero else ''}")
                    if bairro: partes.append(bairro)
                    if cidade: partes.append(f"{cidade}-{uf}")
                    
                    loc_str = " - ".join(partes) if len(partes) > 1 else f"[{dispositivo}] {estado_nome}"
                except Exception as e:
                    print(f"Geocoding falhou: {e}")
                    loc_str = f"[{dispositivo}] Lat: {lat}, Lng: {lng}"
            else:
                loc_str = f"[{dispositivo}] Localização GPS não enviada"

            if ip_addr:
                loc_str += f" (IP: {ip_addr})"

            # Lógica de FORA DO LOCAL via Distância (Haversine)
            EMPRESA_LAT = -23.5458
            EMPRESA_LNG = -46.6433
            fora_local = True 
            
            if location and location.get('lat') and location.get('lng'):
                try:
                    lat_f = float(location['lat'])
                    lng_f = float(location['lng'])
                    R = 6371000
                    phi_1 = math.radians(EMPRESA_LAT)
                    phi_2 = math.radians(lat_f)
                    delta_phi = math.radians(lat_f - EMPRESA_LAT)
                    delta_lambda = math.radians(lng_f - EMPRESA_LNG)
                    a = math.sin(delta_phi/2.0)**2 + math.cos(phi_1) * math.cos(phi_2) * math.sin(delta_lambda/2.0)**2
                    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                    distancia_metros = R * c
                    if distancia_metros <= 1500:
                        fora_local = False
                except:
                    pass
                    
            if fora_local and loc_str:
                ruas_validas = ['major sertório', 'general jardim', 'amaral gurgel', 'consolação', 'rego freitas', 'vila buarque', 'república']
                loc_str_lower = loc_str.lower()
                if any(r in loc_str_lower for r in ruas_validas):
                    fora_local = False

            acao_login = "Login (FORA DO LOCAL)" if fora_local else "Login"
            lat_val = location.get('lat') if location else None
            lng_val = location.get('lng') if location else None
            
            try:
                atualizar_localizacao_usuario(username, loc_str, lat_val, lng_val, ip_addr)
                salvar_log(username, acao_login, f"Dispositivo: {dispositivo}", ip=ip_addr, localizacao=loc_str)
            except Exception as log_e:
                print(f"Erro ao salvar log de login: {log_e}")
                
            return jsonify({'success': True, 'message': 'Login bem-sucedido', 'next_url': url_for('dashboard_page')})
        else:
            return jsonify({'success': False, 'message': 'Usuário ou senha inválidos ou conta desativada'})
    except Exception as global_e:
        print(f"ERRO CRÍTICO NO LOGIN: {global_e}")
        return jsonify({'success': False, 'message': f'Erro interno no servidor: {str(global_e)}'})

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login_page'))


@app.route('/dashboard')
def dashboard_page():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    is_admin = session.get('role') == 'admin'
    return render_template('dashboard.html', user=session['user'], is_admin=is_admin)

@app.route('/analise')
def analise_page():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    is_admin = session.get('role') == 'admin'
    return render_template('analise.html', user=session['user'], is_admin=is_admin)

@app.route('/comunicados')
def comunicados_page():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    is_admin = session.get('role') == 'admin'
    return render_template('comunicados.html', user=session['user'], is_admin=is_admin)

@app.route('/chat')
def chat_page():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    is_admin = session.get('role') == 'admin'
    return render_template('chat.html', user=session['user'], is_admin=is_admin)

@app.route('/administracao')
def administracao_page():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    is_admin = session.get('role') == 'admin'
    if not is_admin:
        return redirect(url_for('dashboard_page'))
    return render_template('administracao.html', user=session['user'], is_admin=is_admin)

@app.route('/banco-de-dados')
def banco_de_dados_page():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    is_admin = session.get('role') == 'admin'
    if not is_admin:
        return redirect(url_for('dashboard_page'))
    return render_template('banco_de_dados.html', user=session['user'], is_admin=is_admin)

@app.route('/gerenciar-bancos')
def gerenciar_bancos_page():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    is_admin = session.get('role') == 'admin'
    if not is_admin:
        return redirect(url_for('dashboard_page'))
    return render_template('gerenciar_bancos.html', user=session['user'], is_admin=is_admin)

@app.route('/gerenciar-scripts')
def gerenciar_scripts_page():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    is_admin = session.get('role') == 'admin'
    if not is_admin:
        return redirect(url_for('dashboard_page'))
    return render_template('gerenciar_scripts.html', user=session['user'], is_admin=is_admin)

@app.route('/scripts-apoio')
def scripts_apoio_page():
    """Página onde os vendedores visualizam os scripts publicados."""
    if 'user' not in session:
        return redirect(url_for('login_page'))
    is_admin = session.get('role') == 'admin'
    return render_template('scripts_apoio.html', user=session['user'], is_admin=is_admin)

# ============================================================
# ROTAS DE API - DASHBOARD
# ============================================================

@app.route('/api/dashboard_data', methods=['GET'])
def get_dashboard_data():
    inicio = request.args.get('inicio')
    fim = request.args.get('fim')
    
    is_admin = session.get('role') == 'admin'
    vendedor_id = None
    if not is_admin and 'user' in session:
        from db.db import obter_usuario_por_username
        u = obter_usuario_por_username(session['user'])
        if u:
            vendedor_id = u['id']

    try:
        atividades = obter_atividades_recentes(50, data_inicio=inicio, data_fim=fim, vendedor_id=vendedor_id)
        stats = obter_dashboard_stats(data_inicio=inicio, data_fim=fim, vendedor_id=vendedor_id)
        ranking = obter_ranking_bancos(5, data_inicio=inicio, data_fim=fim, vendedor_id=vendedor_id)
    except Exception as e:
        print("Erro em dashboard_data:", e)
        atividades = []
        stats = {'contatos':0, 'elegiveis':0, 'nao_elegiveis':0, 'taxa_conversao':0}
        ranking = []

    data = {
        'stats': stats,
        'atividades': atividades,
        'ranking': ranking
    }
    return jsonify(data)

# ============================================================
# ROTAS DE API - CLIENTES
# ============================================================

@app.route('/api/clientes', methods=['GET'])
def api_listar_clientes():
    """Lista todos os clientes cadastrados."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    from db.db import listar_clientes
    try:
        clientes = listar_clientes()
        return jsonify({'success': True, 'clientes': clientes})
    except Exception:
        return jsonify({'success': True, 'clientes': []})

# ============================================================
# ROTAS DE API - ADMINISTRAÇÃO
# ============================================================

@app.route('/api/analise_data', methods=['GET'])
def get_analise_data():
    """Retorna os dados reais de performance para o painel de administração."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
        
    inicio = request.args.get('inicio')
    fim = request.args.get('fim')
    
    vendedores = obter_desempenho_vendedores(data_inicio=inicio, data_fim=fim)
    
    data = {
        'success': True,
        'stats': {
            'total_vendedores': len([v for v in vendedores if v['status'] == 'Ativo']),
            'total_consultas': sum(v['total_consultas'] for v in vendedores),
            'clientes_elegiveis': sum(v['elegiveis'] for v in vendedores),
            'taxa_media_conversao': round(sum(v['taxa_conversao'] for v in vendedores) / len(vendedores), 1) if vendedores else 0
        },
        'vendedores': vendedores
    }
    return jsonify(data)

@app.route('/api/admin_stats', methods=['GET'])
def api_admin_stats():
    """Retorna estatísticas globais para os cartões do dashboard administrativo."""
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    
    inicio = request.args.get('inicio')
    fim = request.args.get('fim')
    
    try:
        stats = get_admin_stats(data_inicio=inicio, data_fim=fim)
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        print(f"Erro ao obter admin stats: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/analytics_dashboard', methods=['GET'])
def api_analytics_dashboard():
    """Retorna os dados consolidados para os gráficos da aba Análises."""
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    
    inicio = request.args.get('inicio')
    fim = request.args.get('fim')
    
    try:
        from db.db import get_analytics_dashboard
        dados = get_analytics_dashboard(data_inicio=inicio, data_fim=fim)
        return jsonify({'success': True, 'data': dados})
    except Exception as e:
        print(f"Erro ao obter dados analíticos: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/performance_ranking', methods=['GET'])
def get_performance_ranking():
    """Retorna os dados detalhados para o ranking de performance."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    
    inicio = request.args.get('inicio')
    fim = request.args.get('fim')
    
    ranking = obter_performance_ranking_vendedores(data_inicio=inicio, data_fim=fim)
    return jsonify({'success': True, 'ranking': ranking})

@app.route('/api/admin/consultas', methods=['GET'])
def api_admin_consultas():
    """Retorna o histórico de consultas para o admin."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    
    inicio = request.args.get('inicio')
    fim = request.args.get('fim')
    busca = request.args.get('busca')
    
    consultas = listar_consultas_admin(data_inicio=inicio, data_fim=fim, busca=busca)
    return jsonify({'success': True, 'consultas': consultas})

# --- API de Scripts ---
@app.route('/api/scripts', methods=['GET'])
def api_listar_scripts():
    apenas_pub = request.args.get('apenas_publicados') == 'true'
    scripts = listar_scripts(apenas_publicados=apenas_pub)
    return jsonify({'success': True, 'scripts': scripts})

@app.route('/api/scripts', methods=['POST'])
def api_adicionar_script():
    if session.get('role') != 'admin': return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    data = request.json
    adicionar_script(data['titulo'], data['categoria'], data['conteudo'])
    return jsonify({'success': True, 'message': 'Script criado!'})

@app.route('/api/scripts/<int:id>', methods=['PUT'])
def api_editar_script(id):
    if session.get('role') != 'admin': return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    data = request.json
    editar_script(id, data['titulo'], data['categoria'], data['conteudo'])
    return jsonify({'success': True, 'message': 'Script atualizado!'})

@app.route('/api/scripts/<int:id>', methods=['DELETE'])
def api_deletar_script(id):
    if session.get('role') != 'admin': return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    deletar_script(id)
    return jsonify({'success': True, 'message': 'Script removido!'})

@app.route('/api/scripts/<int:id>/toggle', methods=['POST'])
def api_toggle_script(id):
    if session.get('role') != 'admin': return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    alternar_publicacao_script(id)
    return jsonify({'success': True, 'message': 'Status alterado!'})

@app.route('/api/scripts/<int:id>/fixar', methods=['POST'])
def api_fixar_script(id):
    if session.get('role') != 'admin': return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    alternar_fixar_script(id)
    return jsonify({'success': True, 'message': 'Status de fixação alterado!'})

@app.route('/api/criar_comunicado', methods=['POST'])
def criar_comunicado():
    """Recebe e salva um novo comunicado no banco de dados."""
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Não autorizado'}), 401

    data = request.get_json()
    titulo = data.get('titulo', '').strip()
    tipo = data.get('tipo', '').strip()
    mensagem = data.get('mensagem', '').strip()
    fixado = 1 if data.get('fixado') else 0

    if not titulo or not tipo or not mensagem:
        return jsonify({'success': False, 'message': 'Todos os campos são obrigatórios.'})

    salvar_comunicado(titulo, tipo, mensagem, session['user'], fixado)
    
    # Dispara alerta em tempo real para todos
    socketio.emit('novo_comunicado', {
        'titulo': titulo,
        'tipo': tipo,
        'mensagem': mensagem,
        'autor': session['user']
    }, namespace='/')
    
    return jsonify({'success': True, 'message': 'Comunicado criado com sucesso!'})

@app.route('/api/comunicados', methods=['GET'])
def listar_comunicados():
    """Retorna todos os comunicados salvos para exibição aos usuários."""
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Não autorizado'}), 401
    comunicados = buscar_comunicados()
    return jsonify({'success': True, 'comunicados': comunicados})

@app.route('/api/comunicados/<int:com_id>', methods=['PUT', 'DELETE'])
def gerenciar_comunicado(com_id):
    """Admin pode editar/deletar qualquer comunicado. Autores podem deletar o próprio."""
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Não autorizado'}), 401

    is_admin = 'admin' in session['user'].lower()
    username = session['user']

    if request.method == 'DELETE':
        # Qualquer usuário pode dispensar/excluir um comunicado da lista
        # Admin pode deletar permanentemente; usuário comum também pode remover
        deletar_comunicado(com_id)
        return jsonify({'success': True, 'message': 'Comunicado removido.'})

    if request.method == 'PUT':
        # Edição completa só para admin
        if not is_admin:
            return jsonify({'success': False, 'message': 'Apenas administradores podem editar comunicados.'}), 403
        data = request.get_json()
        titulo = data.get('titulo', '').strip()
        tipo = data.get('tipo', '').strip()
        mensagem = data.get('mensagem', '').strip()
        fixado = 1 if data.get('fixado') else 0

        if not titulo or not tipo or not mensagem:
            return jsonify({'success': False, 'message': 'Todos os campos são obrigatórios.'})

        editar_comunicado(com_id, titulo, tipo, mensagem, fixado)
        return jsonify({'success': True, 'message': 'Comunicado atualizado com sucesso!'})

@app.route('/api/comunicados/<int:com_id>/fixar', methods=['PUT'])
def fixar_comunicado(com_id):
    """Permite que qualquer usuário alterne o status fixado de um comunicado."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    alternar_fixar_comunicado(com_id)
    return jsonify({'success': True})

@app.route('/api/comunicados/unread_count', methods=['GET'])
def get_unread_count():
    """Retorna o número de comunicados não lidos pelo usuário atual."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    
    try:
        comunicados = buscar_comunicados()
        user = session['user']
        # Um comunicado é não lido se o username não estiver na string 'lido_por'
        unread_count = sum(1 for c in comunicados if (not c.get('lido_por') or user not in c['lido_por']))
        return jsonify({'success': True, 'count': unread_count})
    except Exception as e:
        print(f"Erro ao contar não lidos: {e}")
        return jsonify({'success': False, 'count': 0})

@app.route('/api/comunicados/marcar_lidos', methods=['POST'])
def marcar_comunicados_lidos():
    """Marca todos os comunicados como lidos pelo usuário atual."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    marcar_todos_lidos_usuario(session['user'])
    return jsonify({'success': True})

@app.route('/api/comunicados/<int:com_id>/lido', methods=['POST'])
def marcar_comunicado_lido(com_id):
    """Marca um comunicado específico como lido pelo usuário atual."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    marcar_lido_usuario(com_id, session['user'])
    return jsonify({'success': True})

@app.route('/api/comunicados/<int:com_id>/arquivar', methods=['PUT'])
def arquivar_comunicado(com_id):
    """Arquiva um comunicado para o usuário atual (sem excluir para outros)."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    arquivar_comunicado_usuario(com_id, session['user'])
    return jsonify({'success': True})

@app.route('/api/comunicados/<int:com_id>/desarquivar', methods=['PUT'])
def desarquivar_comunicado(com_id):
    """Remove um comunicado da lista de arquivados do usuário atual."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    desarquivar_comunicado_usuario(com_id, session['user'])
    return jsonify({'success': True})

# ============================================================
# ============================================================
# ROTAS DE API - NOTIFICAÇÕES DO CHAT
# ============================================================

@app.route('/api/chat/unread_count', methods=['GET'])
def get_chat_unread_count():
    """Retorna o número de mensagens não lidas no chat geral pelo usuário atual."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    
    try:
        count = contar_mensagens_chat_nao_lidas(session['user'])
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        print(f"Erro ao contar não lidas do chat: {e}")
        return jsonify({'success': False, 'count': 0})

@app.route('/api/chat/marcar_lido', methods=['POST'])
def marcar_chat_como_lido():
    """Marca todas as mensagens do chat geral como lidas pelo usuário atual."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    
    try:
        canal = 'geral'
        data = request.get_json(silent=True)
        if data and data.get('canal'):
            canal = data['canal']
        atualizar_ultima_leitura_chat(session['user'], canal)
        return jsonify({'success': True})
    except Exception as e:
        print(f"Erro ao marcar chat como lido: {e}")
        return jsonify({'success': False})

# ============================================================
# ============================================================
# CONFIGURAÇÕES E DISTRIBUIÇÃO AUTOMÁTICA
# ============================================================

def rodar_distribuicao_automatica(banco_id_importacao=None):
    """Roda a distribuição automática de leads pendentes para os vendedores configurados, iterativamente (round-robin)."""
    from db.db import obter_configuracao, IS_POSTGRES
    auto_ativa = obter_configuracao('dist_auto_ativa', '0')
    if auto_ativa != '1':
        return 0
    auto_vendedores = obter_configuracao('dist_auto_vendedores', '')
    if not auto_vendedores:
        return 0
    qtd_str = obter_configuracao('dist_auto_qtd', '10')
    qtd_por_vendedor = int(qtd_str)
    
    auto_banco_id = obter_configuracao('dist_auto_banco', '')
    
    # Se configurou um banco e importou um diferente, não distribui agora
    if auto_banco_id and str(auto_banco_id).strip() != '' and banco_id_importacao is not None:
        if str(auto_banco_id) != str(banco_id_importacao):
            return 0
    
    # Define o banco a priorizar: se tem um na config, usa ele. Se não, usa o recém importado (se tiver).
    banco_alvo_id = None
    if auto_banco_id and str(auto_banco_id).strip() != '':
        banco_alvo_id = auto_banco_id
    elif banco_id_importacao is not None:
        banco_alvo_id = banco_id_importacao
    
    vendedores_ids = [v for v in auto_vendedores.split(',') if v.strip()]
    if not vendedores_ids:
        return 0
        
    from db.db import connect as db_connect
    conn = db_connect()
    cursor = conn.cursor()
    
    placeholders = ','.join(['%s' if IS_POSTGRES else '?'] * len(vendedores_ids))
    cursor.execute(f"SELECT id, nome FROM usuarios WHERE id IN ({placeholders}) AND ativo = 1", tuple(vendedores_ids))
    vendedores = cursor.fetchall()
    if not vendedores:
        conn.close()
        return 0
    
    ph = '%s' if IS_POSTGRES else '?'
    now_fn = 'NOW()' if IS_POSTGRES else "datetime('now')"
    date_fn_prefix = '' if IS_POSTGRES else 'DATE('
    date_fn_suffix = '::DATE' if IS_POSTGRES else ')'
        
    query_count = f"SELECT count(*) FROM clientes WHERE status='pendente'"
    params_count = []
    query_select = f"SELECT id FROM clientes WHERE status='pendente'"
    params_select = []
    
    if banco_alvo_id:
        if isinstance(banco_alvo_id, str) and '|' in str(banco_alvo_id):
            b_id, d_imp = str(banco_alvo_id).split('|')
            if IS_POSTGRES:
                query_count += f" AND banco_id = {ph} AND importado_em::DATE = {ph}"
                query_select += f" AND banco_id = {ph} AND importado_em::DATE = {ph}"
            else:
                query_count += f" AND banco_id = {ph} AND DATE(importado_em) = {ph}"
                query_select += f" AND banco_id = {ph} AND DATE(importado_em) = {ph}"
            params_count.extend([b_id, d_imp])
            params_select.extend([b_id, d_imp])
        else:
            query_count += f" AND banco_id = {ph}"
            params_count.append(banco_alvo_id)
            query_select += f" AND banco_id = {ph}"
            params_select.append(banco_alvo_id)
        
    query_select += f" LIMIT {ph}"
        
    cursor.execute(query_count, tuple(params_count))
    total_pendentes = cursor.fetchone()[0]
    
    if total_pendentes == 0:
        conn.close()
        return 0
        
    total_distribuidos = 0
    
    # Distribui uma rodada (uma vez a quantidade configurada para cada vendedor ativo no robô)
    for v_id, v_nome in vendedores:
        if total_pendentes <= 0:
            break
            
        q = min(qtd_por_vendedor, total_pendentes)
        
        p_select = params_select.copy()
        p_select.append(q)
        cursor.execute(query_select, tuple(p_select))
        
        ids = [r[0] for r in cursor.fetchall()]
        if ids:
            placeholders_ids = ','.join([ph] * len(ids))
            cursor.execute(
                f"UPDATE clientes SET status='atribuido', vendedor_id={ph}, vendedor_nome={ph}, atribuido_em={now_fn} WHERE id IN ({placeholders_ids})",
                tuple([v_id, v_nome] + ids)
            )
            total_distribuidos += len(ids)
            total_pendentes -= len(ids)
            
    conn.commit()
    conn.close()
    
    if total_distribuidos > 0:
        from db.db import salvar_log
        salvar_log('Sistema', 'distribuicao_automatica', f"Distribuiu {total_distribuidos} leads automaticamente", 'localhost')
        # Notifica o admin em tempo real
        socketio.emit('distribuicao_leads', {'vendedor': 'Sistema', 'quantidade': total_distribuidos}, room='chat_geral')
    return total_distribuidos

@app.route('/api/admin/rodar_distribuicao', methods=['POST'])
def api_admin_rodar_distribuicao():
    """Trigger manual da distribuição automática."""
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    
    total = rodar_distribuicao_automatica()
    if total > 0:
        return jsonify({'success': True, 'message': f'Robô executado com sucesso! {total} leads foram distribuídos.'})
    else:
        return jsonify({'success': True, 'message': 'O robô rodou, mas não encontrou leads pendentes ou vendedores configurados/ativos para distribuir.'})

@app.route('/api/admin/config', methods=['GET', 'POST'])
def admin_config():
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    
    if request.method == 'GET':
        auto_ativa = obter_configuracao('dist_auto_ativa', '0')
        auto_qtd = obter_configuracao('dist_auto_qtd', '10')
        auto_vendedores = obter_configuracao('dist_auto_vendedores', '') # Lista de IDs separados por vírgula
        auto_banco = obter_configuracao('dist_auto_banco', '')
        return jsonify({
            'success': True, 
            'dist_auto_ativa': auto_ativa == '1', 
            'dist_auto_qtd': int(auto_qtd),
            'dist_auto_vendedores': auto_vendedores.split(',') if auto_vendedores else [],
            'dist_auto_banco': auto_banco
        })
    
    data = request.get_json()
    if 'dist_auto_ativa' in data:
        salvar_configuracao('dist_auto_ativa', '1' if data['dist_auto_ativa'] else '0')
    if 'dist_auto_qtd' in data:
        salvar_configuracao('dist_auto_qtd', data['dist_auto_qtd'])
    if 'dist_auto_vendedores' in data:
        vendedores_str = ",".join(map(str, data['dist_auto_vendedores']))
        salvar_configuracao('dist_auto_vendedores', vendedores_str)
    if 'dist_auto_banco' in data:
        salvar_configuracao('dist_auto_banco', str(data['dist_auto_banco']))
    
    salvar_log(session['user'], "Atualização de Configuração", f"Distribuição automática atualizada")
    
    # Não rodar mais automaticamente ao salvar. O robô deve ser provocado pelos vendedores.
    pass
        
    return jsonify({'success': True})

@app.route('/api/vendedor/receber_leads', methods=['POST'])
def receber_leads_vendedor():
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    
    username = session['user']
    auto_ativa = obter_configuracao('dist_auto_ativa', '0')
    
    from db.db import connect as db_connect
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome FROM usuarios WHERE username = ?", (username,))
    user_row = cursor.fetchone()
    
    if not user_row:
        conn.close()
        return jsonify({'success': False, 'message': 'Vendedor não encontrado'})
    
    vendedor_id, vendedor_nome = user_row
    
    # NOVA REGRA: Verificar se o vendedor já tem leads pendentes na fila dele
    cursor.execute("SELECT COUNT(*) FROM clientes WHERE vendedor_id = ? AND status = 'atribuido'", (vendedor_id,))
    total_atuais = cursor.fetchone()[0]
    if total_atuais > 0:
        conn.close()
        return jsonify({'success': False, 'message': f'Você ainda possui {total_atuais} leads pendentes na sua tela. Trabalhe-os antes de solicitar mais.'})

    # CASO 1: DISTRIBUIÇÃO AUTOMÁTICA ATIVA
    if auto_ativa == '1':
        # Verificar se o vendedor está na lista de permitidos
        auto_vendedores = obter_configuracao('dist_auto_vendedores', '').strip()
        if auto_vendedores:
            permitidos = [v.strip() for v in auto_vendedores.split(',') if v.strip()]
            if permitidos and str(vendedor_id) not in permitidos:
                # Criar solicitação manual pois não tem permissão para o robô
                cursor.execute("SELECT id FROM solicitacoes_leads WHERE vendedor = ? AND status = 'pendente'", (username,))
                if not cursor.fetchone():
                    cursor.execute("""
                        INSERT INTO solicitacoes_leads (vendedor, quantidade_solicitada, status)
                        VALUES (?, ?, 'pendente')
                    """, (username, 10))
                    conn.commit()
                conn.close()
                # Notifica o admin que há uma nova solicitação manual
                socketio.emit('distribuicao_leads', {'vendedor': vendedor_nome, 'tipo': 'solicitacao'}, room='chat_geral')
                return jsonify({'success': False, 'message': 'Você não tem permissão para receber leads automaticamente. Sua solicitação foi enviada para análise manual.'})
        
        qtd_str = obter_configuracao('dist_auto_qtd', '10')
        try:
            qtd = max(1, int(qtd_str))
        except:
            qtd = 10
        
        auto_banco = obter_configuracao('dist_auto_banco', None)
        if not auto_banco or str(auto_banco).strip() == '' or str(auto_banco).lower() == 'none':
            auto_banco = None
            
        from db.db import distribuir_clientes
        ids_count = distribuir_clientes(vendedor_id, vendedor_nome, auto_banco, qtd)
        conn.close()
        
        if ids_count > 0:
            salvar_log(username, "Auto Distribuição", f"Recebeu {ids_count} leads automaticamente")
            socketio.emit('distribuicao_leads', {'vendedor': vendedor_nome, 'quantidade': ids_count}, room='chat_geral')
            return jsonify({'success': True, 'message': f'Robô ativado! Você acaba de receber {ids_count} novos leads da base.'})
        else:
            # Se a base automática estiver vazia, gera uma solicitação manual como fallback
            cursor.execute("SELECT id FROM solicitacoes_leads WHERE vendedor = ? AND status = 'pendente'", (username,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO solicitacoes_leads (vendedor, quantidade_solicitada) VALUES (?, 10)", (username,))
                conn.commit()
            conn.close()
            socketio.emit('distribuicao_leads', {'vendedor': vendedor_nome, 'tipo': 'solicitacao'}, room='chat_geral')
            return jsonify({'success': False, 'message': 'Não há leads automáticos disponíveis. Sua solicitação foi enviada para análise manual.'})

    # CASO 2: DISTRIBUIÇÃO MANUAL (GERAR SOLICITAÇÃO)
    else:
        cursor.execute("SELECT id FROM solicitacoes_leads WHERE vendedor = ? AND status = 'pendente'", (username,))
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Você já possui uma solicitação pendente. Aguarde a aprovação do administrador.'})
        
        cursor.execute("INSERT INTO solicitacoes_leads (vendedor, quantidade_solicitada) VALUES (?, 10)", (username,))
        conn.commit()
        conn.close()
        
        salvar_log(username, "Solicitação de Leads", "Solicitou novos leads manualmente")
        # Notifica o admin via socket
        socketio.emit('distribuicao_leads', {'vendedor': vendedor_nome, 'tipo': 'solicitacao'}, room='chat_geral')
        return jsonify({'success': True, 'message': 'Sua solicitação de leads foi enviada ao administrador!'})

@app.route('/api/admin/solicitacoes', methods=['GET'])
def listar_solicitacoes():
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    
    from db.db import connect as db_connect, Row
    conn = db_connect()
    conn.row_factory = Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.*, u.nome as vendedor_nome 
        FROM solicitacoes_leads s
        LEFT JOIN usuarios u ON s.vendedor = u.username
        WHERE s.status = 'pendente'
        ORDER BY s.criado_em DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    solicitacoes = [dict(row) for row in rows]
    return jsonify({'success': True, 'solicitacoes': solicitacoes})

@app.route('/api/admin/solicitacoes/aprovar', methods=['POST'])
def aprovar_solicitacao():
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    
    data = request.get_json()
    sol_id = data.get('id')
    quantidade = int(data.get('quantidade', 10))
    
    from db.db import connect as db_connect
    conn = db_connect()
    cursor = conn.cursor()
    
    # Obter dados do vendedor
    cursor.execute("SELECT vendedor FROM solicitacoes_leads WHERE id = ?", (sol_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'message': 'Solicitação não encontrada'})
    
    username = row[0]
    cursor.execute("SELECT id, nome FROM usuarios WHERE username = ?", (username,))
    user_row = cursor.fetchone()
    
    if not user_row:
        conn.close()
        return jsonify({'success': False, 'message': 'Vendedor não encontrado'})
    
    vendedor_id, vendedor_nome = user_row
    
    # Realizar a distribuição
    from db.db import distribuir_clientes
    ids_count = distribuir_clientes(vendedor_id, vendedor_nome, None, quantidade)
    
    if ids_count > 0:
        cursor.execute("UPDATE solicitacoes_leads SET status = 'aprovada', quantidade_enviada = ?, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?", (ids_count, sol_id))
        conn.commit()
        conn.close()
        salvar_log(session['user'], "Aprovação de Leads", f"Aprovou {ids_count} leads para {username}")
        
        # Notifica todos os admins para atualizar os cards
        socketio.emit('distribuicao_leads', {'vendedor': vendedor_nome, 'quantidade': ids_count}, room='chat_geral')
        
        return jsonify({'success': True, 'message': f'Aprovados {ids_count} leads para {vendedor_nome}!'})
    else:
        conn.close()
        return jsonify({'success': False, 'message': 'Não há leads disponíveis para distribuir no momento.'})

@app.route('/api/admin/solicitacoes/rejeitar', methods=['POST'])
def rejeitar_solicitacao():
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    
    data = request.get_json()
    sol_id = data.get('id')
    
    from db.db import connect as db_connect
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE solicitacoes_leads SET status = 'rejeitada', atualizado_em = CURRENT_TIMESTAMP WHERE id = ?", (sol_id,))
    conn.commit()
    conn.close()
    
    salvar_log(session['user'], "Rejeição de Leads", f"Rejeitou a solicitação ID {sol_id}")
    return jsonify({'success': True})

@app.route('/api/usuarios', methods=['GET'])
def api_listar_usuarios():
    """Lista todos os usuários."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    return jsonify({'success': True, 'usuarios': listar_usuarios()})

@app.route('/api/usuarios', methods=['POST'])
def api_adicionar_usuario():
    """Cria um novo usuário."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    nome = data.get('nome', '').strip()
    email = data.get('email', '').strip()
    papel = data.get('papel', 'vendedor')
    if not username or not password:
        return jsonify({'success': False, 'message': 'Usuário e senha são obrigatórios.'})
    try:
        novo_id = adicionar_usuario(username, password, nome, email, papel)
        salvar_log(session['user'], "Criou Usuário", f"Novo: {username} ({papel})", ip=get_client_ip())
        return jsonify({'success': True, 'id': novo_id, 'message': f'Usuário "{nome or username}" criado!'})
    except Exception as e:
        erro_str = str(e).lower()
        print(f"Erro real ao adicionar usuario: {e}")
        return jsonify({'success': False, 'message': f'Erro do banco: {e}'})

@app.route('/api/usuarios/foto', methods=['POST'])
def api_atualizar_foto():
    """Atualiza a foto de perfil do usuário logado."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    data = request.get_json()
    foto_base64 = data.get('foto', '')
    from db.db import atualizar_foto_usuario
    atualizar_foto_usuario(session['user'], foto_base64)
    session['user_foto'] = foto_base64
    return jsonify({'success': True, 'message': 'Foto atualizada com sucesso.'})

@app.route('/api/usuarios/<int:uid>/toggle', methods=['POST'])
def api_toggle_usuario(uid):
    """Ativa ou desativa um usuário."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    desativar_usuario(uid)
    salvar_log(session['user'], "Alterou Status", f"Usuário ID: {uid}", ip=get_client_ip())
    return jsonify({'success': True, 'message': 'Status atualizado.'})

@app.route('/api/usuarios/<int:uid>', methods=['DELETE', 'PUT'])
def api_gerenciar_usuario(uid):
    """Admin: deletar ou editar um usuário."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    
    if request.method == 'DELETE':
        deletar_usuario(uid)
        salvar_log(session['user'], "Deletou Usuário", f"ID: {uid}", ip=get_client_ip())
        return jsonify({'success': True, 'message': 'Usuário removido.'})
    
    if request.method == 'PUT':
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        nome = data.get('nome', '').strip()
        email = data.get('email', '').strip()
        papel = data.get('papel', 'vendedor')
        
        if not username:
            return jsonify({'success': False, 'message': 'O campo usuário é obrigatório.'})
            
        editar_usuario(uid, username, password, nome, email, papel)
        salvar_log(session['user'], "Editou Usuário", f"ID: {uid} - {username} ({papel})", ip=get_client_ip())
        return jsonify({'success': True, 'message': 'Usuário atualizado com sucesso!'})




@app.route('/api/logs', methods=['GET'])
def api_listar_logs():
    """Retorna os logs de auditoria com filtros (apenas para admin)."""
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Não autorizado'}), 401
    
    inicio = request.args.get('inicio')
    fim = request.args.get('fim')
    usuario = request.args.get('usuario')
    acao = request.args.get('acao')
    page = request.args.get('page', 1, type=int)
    
    limit = 50
    offset = (page - 1) * limit
    
    resultado = buscar_logs(limit=limit, offset=offset, data_inicio=inicio, data_fim=fim, usuario_filtro=usuario, acao_filtro=acao)
    return jsonify({
        'success': True, 
        'logs': resultado['logs'], 
        'total': resultado['total'],
        'page': page,
        'limit': limit
    })

@app.route('/api/clientes_por_banco', methods=['GET'])
def api_clientes_por_banco():
    """Retorna contagem de clientes pendentes por banco."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    return jsonify({'success': True, 'bancos': get_clientes_por_banco()})

@app.route('/api/distribuicao_vendedores', methods=['GET'])
def api_distribuicao_vendedores():
    """Retorna distribuição atual por vendedor (total atribuído + últimos clientes)."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    return jsonify({'success': True, 'distribuicao': get_distribuicao_por_vendedor()})

@app.route('/api/vendedores', methods=['GET'])
def api_listar_vendedores():
    """Lista vendedores ativos."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    return jsonify({'success': True, 'vendedores': listar_vendedores()})

@app.route('/api/vendedores', methods=['POST'])
def api_adicionar_vendedor():
    """Adiciona um novo vendedor."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    data = request.get_json()
    nome = data.get('nome', '').strip()
    username = data.get('username', '').strip()
    telefone = data.get('telefone', '').strip()
    if not nome:
        return jsonify({'success': False, 'message': 'Nome do vendedor é obrigatório.'})
    novo_id = adicionar_vendedor(nome, username, telefone)
    return jsonify({'success': True, 'id': novo_id, 'message': f'Vendedor "{nome}" adicionado!'})

@app.route('/api/vendedores/<int:vendedor_id>', methods=['DELETE'])
def api_remover_vendedor(vendedor_id):
    """Remove (desativa) um vendedor."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    remover_vendedor(vendedor_id)
    return jsonify({'success': True, 'message': 'Vendedor removido.'})

@app.route('/api/distribuir_clientes', methods=['POST'])
def api_distribuir_clientes():
    """Admin distribui N clientes de um banco para um vendedor."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    data = request.get_json()
    vendedor_id = data.get('vendedor_id')
    vendedor_nome = data.get('vendedor_nome', '')
    banco_id = data.get('banco_id')
    quantidade = data.get('quantidade', 0)
    if not vendedor_id or int(quantidade) <= 0:
        return jsonify({'success': False, 'message': 'Informe vendedor e quantidade.'})
    enviados = distribuir_clientes(int(vendedor_id), vendedor_nome, banco_id, int(quantidade))
    if enviados == 0:
        return jsonify({'success': False, 'message': 'Nenhum cliente disponível para distribuição.'})
    
    # Notifica todos os admins para atualizar os cards
    socketio.emit('distribuicao_leads', {'vendedor': vendedor_nome, 'quantidade': enviados}, room='chat_geral')
    
    return jsonify({'success': True, 'message': f'{enviados} cliente(s) distribuídos para {vendedor_nome}!', 'enviados': enviados})

@app.route('/api/bancos', methods=['GET'])
def api_listar_bancos():
    """Lista todos os bancos cadastrados."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    todos = request.args.get('todos', '0') == '1'
    return jsonify({'success': True, 'bancos': listar_bancos(apenas_ativos=not todos)})

@app.route('/api/bancos', methods=['POST'])
def api_adicionar_banco():
    """Adiciona um novo banco."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    data = request.get_json()
    nome = data.get('nome', '').strip()
    if not nome:
        return jsonify({'success': False, 'message': 'Nome do banco é obrigatório.'})
    try:
        novo_id = adicionar_banco(nome)
        return jsonify({'success': True, 'id': novo_id, 'message': f'Banco "{nome}" adicionado com sucesso!'})
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)})
    except Exception as e:
        print(f"Erro ao adicionar banco: {e}")
        return jsonify({'success': False, 'message': 'Erro inesperado ao salvar o banco.'})

@app.route('/api/admin/recolher_leads', methods=['POST'])
def api_recolher_leads():
    """Retira todos os leads pendentes de um vendedor e volta para a base."""
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    
    data = request.get_json()
    vendedor_id = data.get('vendedor_id')
    
    if not vendedor_id:
        return jsonify({'success': False, 'message': 'ID do vendedor não informado.'})
    
    from db.db import recolher_clientes_vendedor
    total = recolher_clientes_vendedor(vendedor_id)
    
    salvar_log(session['user'], "Recolhimento de Leads", f"Recolheu {total} leads do vendedor ID {vendedor_id}")
    
    # Notifica via socket para atualizar os cards
    socketio.emit('distribuicao_leads', {'vendedor': 'Sistema', 'quantidade': -total}, room='chat_geral')
    
    return jsonify({'success': True, 'message': f'{total} leads recolhidos com sucesso!'})

@app.route('/api/bancos/<int:banco_id>/toggle', methods=['POST'])
def api_toggle_banco(banco_id):
    """Ativa ou inativa um banco."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    
    from db.db import alternar_status_banco, obter_banco_por_id
    banco = obter_banco_por_id(banco_id)
    if not banco:
        return jsonify({'success': False, 'message': 'Banco não encontrado.'}), 404
    
    # Log da ação
    acao_str = "Inativou" if banco['ativo'] else "Ativou"
    salvar_log(session['user'], f"{acao_str} Banco", f"Banco: {banco['nome']} (ID: {banco_id})", ip=get_client_ip())
    
    alternar_status_banco(banco_id)
    return jsonify({'success': True, 'message': f'Banco {acao_str.lower()} com sucesso.'})

@app.route('/api/bancos/<int:banco_id>/historico', methods=['GET'])
def api_banco_historico(banco_id):
    if 'user' not in session: return jsonify({'success': False}), 401
    from db.db import obter_banco_por_id, buscar_logs
    banco = obter_banco_por_id(banco_id)
    if not banco: return jsonify({'success': False}), 404
    
    # Busca logs gerais e filtra pelos relacionados a este banco (por nome ou ID no detalhe)
    logs = buscar_logs(limit=1000)
    historico = [l for l in logs if f"(ID: {banco_id})" in (l['detalhe'] or '') and "Banco" in l['acao']]
    
    return jsonify({'success': True, 'nome': banco['nome'], 'historico': historico})

@app.route('/api/bancos/<int:banco_id>', methods=['DELETE'])
def api_remover_banco(banco_id):
    """Remove permanentemente um banco pelo ID."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    remover_banco(banco_id)
    return jsonify({'success': True, 'message': 'Banco excluído permanentemente!'})

@app.route('/api/chat/historico')
def api_chat_historico():
    """Retorna o histórico das últimas mensagens do chat."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    com_usuario = request.args.get('com', 'geral')
    msgs = buscar_mensagens_chat(session['user'], com_usuario, 100)
    return jsonify({'success': True, 'mensagens': msgs})

@app.route('/api/chat/usuarios_online')
def api_usuarios_online():
    """Retorna lista de usuários online."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    lista = [{'username': u, 'nome': n} for u, n in usuarios_online.items()]
    return jsonify({'success': True, 'usuarios': lista})

@app.route('/api/chat/fixar', methods=['POST'])
def api_fixar_conversa():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Não logado'}), 401
    
    data = request.json
    target_id = data.get('target_id')
    if not target_id:
        return jsonify({'success': False, 'error': 'ID alvo não informado'}), 400
        
    res = alternar_fixar_conversa(session['user'], target_id)
    return jsonify(res)

@app.route('/api/chat/fixadas')
def api_buscar_fixadas():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Não logado'}), 401
    
    fixadas = buscar_conversas_fixadas(session['user'])
    return jsonify({'success': True, 'fixadas': fixadas})

# ============================================================
# ROTAS DE API - CANAIS DE CHAT
# ============================================================

@app.route('/api/canais', methods=['GET'])
def api_listar_canais():
    """Lista canais acessíveis pelo usuário logado."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    from db.db import listar_canais
    canais = listar_canais(session['user'])
    return jsonify({'success': True, 'canais': canais})

@app.route('/api/canais', methods=['POST'])
def api_criar_canal():
    """Admin cria um novo canal."""
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Não autorizado'}), 401
    
    data = request.get_json()
    nome = data.get('nome')
    privacidade = data.get('privacidade', 'privado')
    membros = data.get('membros', [])
    canal_id = f"canal_{int(datetime.now().timestamp())}"
    
    from db.db import salvar_canal
    salvar_canal(canal_id, nome, privacidade, session['user'], membros)
    salvar_log(session['user'], "Criou Canal", f"Canal: {nome} ({privacidade})", ip=get_client_ip())
    return jsonify({'success': True, 'canal_id': canal_id})

@app.route('/api/canais/<canal_id>', methods=['PUT'])
def api_editar_canal(canal_id):
    """Admin edita um canal."""
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Não autorizado'}), 401
    
    data = request.get_json()
    nome = data.get('nome')
    privacidade = data.get('privacidade')
    membros = data.get('membros')
    
    from db.db import salvar_canal
    salvar_canal(canal_id, nome, privacidade, session['user'], membros)
    salvar_log(session['user'], "Editou Canal", f"ID: {canal_id} - {nome}", ip=get_client_ip())
    return jsonify({'success': True})

@app.route('/api/canais/<canal_id>', methods=['DELETE'])
def api_deletar_canal(canal_id):
    """Admin deleta um canal."""
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Não autorizado'}), 401
    
    from db.db import deletar_canal
    deletar_canal(canal_id)
    salvar_log(session['user'], "Deletou Canal", f"ID: {canal_id}", ip=get_client_ip())
    return jsonify({'success': True})

@app.route('/api/canais/<canal_id>/membros/<username>', methods=['DELETE'])
def api_remover_membro_canal(canal_id, username):
    """Admin remove um membro do canal."""
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Não autorizado'}), 401
    
    from db.db import remover_membro_canal
    remover_membro_canal(canal_id, username)
    return jsonify({'success': True})

@socketio.on('connect')
def on_connect(auth=None):
    """Usuário conecta ao chat."""
    if 'user' in session:
        username = session['user']
        nome = session.get('user_nome') or username.split('@')[0].split('.')[0].replace('_', ' ').title()
        usuarios_online[username] = nome
        
        join_room('chat_geral')
        join_room(username)
        
        # Entra automaticamente nas salas dos canais que é membro
        from db.db import listar_canais
        meus_canais = listar_canais(username)
        for c in meus_canais:
            join_room(str(c['id']))

        emit('usuario_online', {
            'username': username,
            'nome': nome,
            'usuarios': list(usuarios_online.values()),
            'usuarios_online_dict': usuarios_online
        }, room='chat_geral', broadcast=True)

@socketio.on('disconnect')
def on_disconnect():
    """Usuário desconecta do chat."""
    if 'user' in session:
        username = session['user']
        nome = usuarios_online.pop(username, username)
        leave_room('chat_geral')
        leave_room(username)
        emit('usuario_offline', {
            'username': username,
            'nome': nome,
            'usuarios': list(usuarios_online.values()),
            'usuarios_online_dict': usuarios_online
        }, room='chat_geral', broadcast=True)

@socketio.on('join_chat')
def on_join_chat(data=None):
    """Solicita histórico e lista de online ao entrar ou trocar de chat."""
    if 'user' in session:
        username = session['user']
        nome = session.get('user_nome') or username.split('@')[0].split('.')[0].replace('_', ' ').title()
        usuarios_online[username] = nome
        destinatario = 'geral'
        if data and 'destinatario' in data:
            destinatario = data['destinatario']
        
        join_room('chat_geral')
        join_room(username)
        if destinatario.startswith('canal_'):
            join_room(str(destinatario))
            
        from db.db import buscar_mensagens_chat
        msgs = buscar_mensagens_chat(username, destinatario, 100)
        emit('historico_chat', {
            'destinatario': destinatario,
            'mensagens': msgs,
            'usuarios_online': list(usuarios_online.values()),
            'usuarios_online_dict': usuarios_online
        })
        
        if not data or data.get('notify', True):
            emit('usuario_online', {
                'username': username,
                'nome': nome,
                'usuarios': list(usuarios_online.values()),
                'usuarios_online_dict': usuarios_online
            }, room='chat_geral', broadcast=True)

@socketio.on('send_message')
def on_send_message(data):
    """Recebe e distribui uma mensagem do chat."""
    if 'user' not in session:
        return
    username = session['user']
    nome = usuarios_online.get(username,
           username.split('@')[0].split('.')[0].replace('_', ' ').title())
    mensagem = data.get('mensagem', '').strip()
    destinatario = data.get('destinatario', 'geral')
    
    if not mensagem or len(mensagem) > 1000:
        return
        
    msg_id = salvar_mensagem_chat(username, nome, mensagem, destinatario)
    from datetime import datetime
    agora = datetime.now()
    payload = {
        'id': msg_id,
        'remetente': username,
        'nome': nome,
        'destinatario': destinatario,
        'mensagem': mensagem,
        'hora': agora.strftime('%H:%M'),
        'data': agora.strftime('%d/%m/%Y')
    }
    
    if destinatario == 'geral':
        emit('nova_mensagem', payload, room='chat_geral')
    else:
        emit('nova_mensagem', payload, room=destinatario)
        if destinatario != username:
            emit('nova_mensagem', payload, room=username)

@socketio.on('monitor_request_history')
def on_monitor_request_history(data):
    """Admin solicita histórico de um usuário específico para monitorar."""
    if 'user' not in session or session.get('role') != 'admin':
        return
    alvo = data.get('username')
    offset = data.get('offset', 0)
    from db.db import buscar_historico_monitor
    msgs = buscar_historico_monitor(alvo, limit=100, offset=offset)
    
    if offset == 0:
        join_room(alvo)
    
    emit('monitor_historico', {
        'alvo': alvo,
        'mensagens': msgs,
        'offset': offset
    })

# ============================================================
# ROTAS TELA DO VENDEDOR E IMPORTAÇÃO
# ============================================================

@app.route('/api/importar_excel', methods=['POST'])
def api_importar_excel():
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Acesso negado.'})
    
    banco_id = request.form.get('banco_id')
    file = request.files.get('file')
    
    if not banco_id or not file:
        return jsonify({'success': False, 'message': 'Banco ou arquivo não informados.'})
        
    try:
        # Busca nome do banco
        from db.db import listar_bancos
        bancos = listar_bancos()
        banco_nome = next((b['nome'] for b in bancos if str(b['id']) == str(banco_id)), 'Desconhecido')
        
        df = pd.read_excel(file)
        
        # Mapeamento básico de colunas
        def find_col(possible_names):
            for col in df.columns:
                if str(col).strip().upper() in possible_names:
                    return col
            return None
            
        col_nome = find_col(['NOME', 'NOME DO CLIENTE', 'CLIENTE', 'RAZA', 'NOME/RAZA'])
        col_cpf = find_col(['CPF', 'CNPJ', 'CPF/CNPJ'])
        col_tel1 = find_col(['TELEFONE', 'TELEFONE 1', 'TELEFONE1', 'TEL'])
        col_tel2 = find_col(['TELEFONE 2', 'TELEFONE2'])
        col_tel3 = find_col(['TELEFONE 3', 'TELEFONE3'])
        col_tel4 = find_col(['TELEFONE 4', 'TELEFONE4'])
        col_margem = find_col(['MARGEM', 'VALOR MARGEM', 'MARGEM DISPONIVEL'])
        col_wpp = find_col(['WHATSAPP', 'WPP'])
        col_sexo = find_col(['SEXO'])
        col_idade = find_col(['IDADE'])
        col_rua = find_col(['RUA', 'ENDERECO', 'LOGRADOURO'])
        col_bairro = find_col(['BAIRRO'])
        col_cep = find_col(['CEP'])
        col_cidade = find_col(['CIDADE', 'MUNICIPIO'])
        col_estado = find_col(['ESTADO', 'UF'])
        
        if not col_nome or not col_cpf or not col_tel1 or not col_margem:
            return jsonify({'success': False, 'message': 'A planilha deve conter no mínimo as colunas NOME, CPF, TELEFONE 1 e MARGEM.'})

        clientes_dados = []
        for index, row in df.iterrows():
            nome = str(row[col_nome]) if pd.notna(row[col_nome]) else ''
            cpf = str(row[col_cpf]) if pd.notna(row[col_cpf]) else ''
            tel1 = str(row[col_tel1]) if pd.notna(row[col_tel1]) else ''
            tel2 = str(row[col_tel2]) if col_tel2 and pd.notna(row[col_tel2]) else ''
            tel3 = str(row[col_tel3]) if col_tel3 and pd.notna(row[col_tel3]) else ''
            tel4 = str(row[col_tel4]) if col_tel4 and pd.notna(row[col_tel4]) else ''
            
            # Tratamento da margem
            margem_val = 0.0
            raw_margem = row[col_margem]
            if pd.notna(raw_margem):
                if isinstance(raw_margem, (int, float)):
                    margem_val = float(raw_margem)
                else:
                    try:
                        clean_str = str(raw_margem).replace('R$', '').replace('.', '').replace(',', '.').strip()
                        margem_val = float(clean_str)
                    except:
                        pass
                        
            whatsapp = str(row[col_wpp]) if col_wpp and pd.notna(row[col_wpp]) else ''
            sexo = str(row[col_sexo]) if col_sexo and pd.notna(row[col_sexo]) else ''
            idade = int(row[col_idade]) if col_idade and pd.notna(row[col_idade]) else 0
            rua = str(row[col_rua]) if col_rua and pd.notna(row[col_rua]) else ''
            bairro = str(row[col_bairro]) if col_bairro and pd.notna(row[col_bairro]) else ''
            cep = str(row[col_cep]) if col_cep and pd.notna(row[col_cep]) else ''
            cidade = str(row[col_cidade]) if col_cidade and pd.notna(row[col_cidade]) else ''
            estado = str(row[col_estado]) if col_estado and pd.notna(row[col_estado]) else ''
            
            if nome and cpf and tel1:
                clientes_dados.append((
                    nome, cpf, tel1, tel2, tel3, tel4, margem_val, whatsapp, sexo, idade, 
                    rua, bairro, cep, cidade, estado, banco_id, banco_nome
                ))
                
        # Lê o arquivo em memória para armazenar no banco de dados
        from werkzeug.utils import secure_filename
        nome_original = secure_filename(file.filename)
        file.seek(0)
        arquivo_bytes = file.read()
        
        # Registra o lote no banco de dados (arquivo salvo como BLOB)
        from db.db import registrar_lote_importado
        lote_id = registrar_lote_importado(nome_original, banco_id, banco_nome, len(clientes_dados), session['user'], arquivo_bytes)
        
        # Adiciona o lote_id aos clientes
        clientes_com_lote = []
        for c in clientes_dados:
            clientes_com_lote.append(c + (lote_id,))
            
        inseridos = salvar_clientes_lote(clientes_com_lote)
        salvar_log(session['user'], 'importou_excel', f"Importou {inseridos} clientes para o banco {banco_nome}", get_client_ip())
        
        # Dispara o robô para distribuir esses novos leads imediatamente (se configurado)
        total_dist = rodar_distribuicao_automatica(banco_id)
        
        from datetime import datetime
        hoje = datetime.now().strftime("%Y-%m-%d")
        
        msg = f'{inseridos} clientes importados com sucesso.'
        if total_dist > 0:
            msg += f' {total_dist} leads já foram distribuídos pelo robô.'
            
        return jsonify({'success': True, 'message': msg})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro ao processar arquivo: {str(e)}'})

@app.route('/api/lotes', methods=['GET'])
def api_listar_lotes():
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Acesso negado.'})
    from db.db import listar_lotes_importados
    lotes = listar_lotes_importados()
    return jsonify({'success': True, 'lotes': lotes})

@app.route('/api/lotes/<int:lote_id>', methods=['DELETE'])
def api_excluir_lote(lote_id):
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Acesso negado.'})
    
    from db.db import obter_lote_por_id, excluir_lote_e_clientes
    lote = obter_lote_por_id(lote_id)
    if not lote:
        return jsonify({'success': False, 'message': 'Lote não encontrado.'})
        
    apagados = excluir_lote_e_clientes(lote_id)
            
    from db.db import salvar_log
    salvar_log(session['user'], 'excluiu_lote', f"Excluiu o lote {lote['nome_arquivo']} e {apagados} clientes associados.", get_client_ip())
    
    return jsonify({'success': True, 'message': f'Lote excluído. {apagados} clientes foram removidos do sistema.'})

@app.route('/api/lotes/download/<int:lote_id>', methods=['GET'])
def api_download_lote(lote_id):
    if 'user' not in session or session.get('role') != 'admin':
        return "Acesso negado", 403
        
    from db.db import obter_lote_por_id
    lote = obter_lote_por_id(lote_id, incluir_blob=True)
    if not lote:
        return "Lote não encontrado.", 404
    
    arquivo_bytes = lote.get('arquivo_blob')
    if not arquivo_bytes:
        return "O arquivo não está disponível no banco de dados.", 404
        
    import io
    from flask import send_file
    return send_file(
        io.BytesIO(arquivo_bytes),
        as_attachment=True,
        download_name=lote['nome_arquivo'],
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@app.route('/vendedor')
def vendedor_page():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    # Restringe o acesso apenas para vendedores e admins
    if session.get('role') not in ['vendedor', 'admin']:
        return redirect(url_for('dashboard_page'))
    is_admin = session.get('role') == 'admin'
    return render_template('vendedor.html', user=session['user'], is_admin=is_admin)

@app.route('/api/vendedor/dashboard')
def api_vendedor_dashboard():
    if 'user' not in session:
        return jsonify({'success': False})
    
    from db.db import obter_usuario_por_username
    u = obter_usuario_por_username(session['user'])
    if not u: return jsonify({'success': False})
    
    stats = obter_stats_tela_vendedor(u['id'])
    return jsonify({'success': True, 'stats': stats})

@app.route('/api/vendedor/cliente/<int:cliente_id>', methods=['GET'])
def api_vendedor_get_cliente(cliente_id):
    if 'user' not in session:
        return jsonify({'success': False})
    
    from db.db import obter_usuario_por_username, obter_cliente_por_id
    u = obter_usuario_por_username(session['user'])
    if not u: return jsonify({'success': False})
    
    cli = obter_cliente_por_id(cliente_id, u['id'])
    if cli:
        return jsonify({'success': True, 'cliente': cli})
    return jsonify({'success': False, 'message': 'Cliente não encontrado.'})

@app.route('/api/vendedor/cliente/<int:cliente_id>', methods=['PUT'])
def api_vendedor_editar_cliente(cliente_id):
    if 'user' not in session:
        return jsonify({'success': False})
        
    from db.db import obter_usuario_por_username, editar_cliente_vendedor
    u = obter_usuario_por_username(session['user'])
    if not u: return jsonify({'success': False})
    
    data = request.json
    success = editar_cliente_vendedor(cliente_id, u['id'], data)
    if success:
        return jsonify({'success': True, 'message': 'Cliente atualizado com sucesso!'})
    return jsonify({'success': False, 'message': 'Erro ao atualizar cliente.'})

@app.route('/api/vendedor/proximo_cliente')
def api_vendedor_proximo_cliente():
    if 'user' not in session:
        return jsonify({'success': False})
    
    from db.db import obter_usuario_por_username
    u = obter_usuario_por_username(session['user'])
    if not u: return jsonify({'success': False})
    
    cliente = obter_proximo_cliente_vendedor(u['id'])
    return jsonify({'success': True, 'cliente': cliente})

@app.route('/api/vendedor/salvar_tabulacao', methods=['POST'])
def api_vendedor_salvar_tabulacao():
    if 'user' not in session:
        return jsonify({'success': False})
    
    from db.db import obter_usuario_por_username
    u = obter_usuario_por_username(session['user'])
    if not u: return jsonify({'success': False})
    
    data = request.json
    cliente_id = data.get('cliente_id')
    status = data.get('status')
    bancos_elegiveis = data.get('bancos_elegiveis', '')
    margem = data.get('margem_verificada', 0.0)
    observacao = data.get('observacao', '')
    
    sucesso = salvar_tabulacao_cliente(cliente_id, u['id'], status, bancos_elegiveis, margem, observacao)
    
    if sucesso:
        salvar_log(session['user'], 'tabulou_cliente', f"Tabulou cliente #{cliente_id} como {status}", get_client_ip())
        # Notifica todos para atualizar os dashboards
        socketio.emit('atualizar_dashboard', {'tipo': 'tabulacao', 'status': status}, room='chat_geral')
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Falha ao salvar. O cliente pode não pertencer a você.'})

@app.route('/api/vendedor/historico')
def api_vendedor_historico():
    if 'user' not in session:
        return jsonify({'success': False})
    
    from db.db import obter_usuario_por_username
    u = obter_usuario_por_username(session['user'])
    if not u: return jsonify({'success': False})
    
    clientes = obter_ultimos_clientes_trabalhados(u['id'], 5)
    return jsonify({'success': True, 'clientes': clientes})

@app.route('/api/usuarios/foto/<username>')
def api_get_user_photo(username):
    """Retorna a foto do usuário do banco de dados (Base64)."""
    from db.db import obter_usuario_por_username
    u = obter_usuario_por_username(username)
    if u and u.get('foto'):
        return jsonify({'success': True, 'foto': u['foto']})
    return jsonify({'success': False, 'message': 'Foto não encontrada'}), 404

@app.route('/api/usuarios/foto', methods=['POST'])
def api_update_my_photo():
    """Atualiza a foto do usuário logado."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    data = request.get_json()
    foto = data.get('foto')
    if not foto:
        return jsonify({'success': False}), 400
    from db.db import atualizar_foto_usuario
    atualizar_foto_usuario(session['user'], foto)
    return jsonify({'success': True})

@app.route('/api/clear_welcome')
def clear_welcome():
    session.pop('show_welcome', None)
    return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)