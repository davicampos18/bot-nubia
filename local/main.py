import os
# --- Desativar verificação SSL para download da IA ---
os.environ['HF_HUB_DISABLE_SSL_VERIFICATION'] = '1'

import requests
import threading
import time
import urllib3
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
from contextlib import asynccontextmanager 

# Desabilitar avisos de SSL (para requests gerais)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Importa a IA local
from nubia_brain import vetorizar_base_conhecimento, get_modelo_sentenca
from nubia_core import processar_mensagem

# CONFIGURAÇÃO
from config import URL_NUVEM
URL_BOT_LOCAL = "http://127.0.0.1:3000"

GLOBAL_BRAIN = {}
user_sessions = {}

# --- Inicialização (Lifespan) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🏠 Iniciando NUBIA Local...")
    
    try:
        get_modelo_sentenca() 
        c, t = vetorizar_base_conhecimento()
        GLOBAL_BRAIN["cerebro"] = c
        GLOBAL_BRAIN["topicos"] = t
        print("✅ Cérebro carregado com sucesso!")
    except Exception as e:
        print(f"❌ Erro fatal ao carregar IA: {e}")

    threading.Thread(target=loop_sincronizacao, daemon=True).start()
    
    yield 
    
    print("🛑 Desligando NUBIA...")

app = FastAPI(lifespan=lifespan)

# --- MODELOS ---
class ZapMsg(BaseModel):
    telefone: str
    nome: str
    mensagem: str
    is_group: bool = False
    original_id: Optional[str] = None
    base64: Optional[str] = None
    mimetype: Optional[str] = None
    filename: Optional[str] = None

class ListaZap(BaseModel):
    id: str
    nome: str
    qtd: int

# --- 1. RECEBE DO ZAP LOCAL ---
@app.post("/webhook/local")
def receber_zap(dados: ZapMsg):
    print(f"📩 Local recebeu de {dados.nome}: {dados.mensagem}")
    
    id_para_responder = dados.original_id if dados.original_id else dados.telefone

    # Prepara o payload básico
    payload_nuvem = {
        "telefone": id_para_responder, 
        "nome": dados.nome, 
        "texto": dados.mensagem, 
        "remetente": "cliente", 
        "status_envio": "recebido"
    }

    # --- LÓGICA DE ANEXO ---
    if dados.base64:
        print(f"   📎 Processando anexo: {dados.filename}")
        payload_nuvem["arquivo_base64"] = dados.base64
        payload_nuvem["arquivo_nome"] = dados.filename
        
        # Define o tipo simplificado
        tipo = 'documento'
        mime = (dados.mimetype or '').lower()
        if 'image' in mime: tipo = 'imagem'
        elif 'audio' in mime: tipo = 'audio'
        elif 'pdf' in mime: tipo = 'documento'
        
        payload_nuvem["arquivo_tipo"] = tipo
        
        if not payload_nuvem["texto"]: 
            payload_nuvem["texto"] = f"[{tipo}]"
    # -----------------------

    # Envia para a Nuvem
    try:
        requests.post(f"{URL_NUVEM}/sync/mensagem", json=payload_nuvem, verify=False)
    except Exception as e: 
        print(f"Erro sync nuvem (Log): {e}")

    if dados.is_group:
        return {"ok": True, "obs": "Grupo ignorado pela IA"}

    # 2. Verifica Status (Se já tem algum atendente)
    try:
        res_status = requests.get(f"{URL_NUVEM}/sync/status_conversa/{id_para_responder}", verify=False)
        if res_status.status_code == 200:
            status_conversa = res_status.json().get("status", "robo")
            
            # Se com status humano, fila ou atendimento, NUBIA fica quieta
            if status_conversa in ['atendimento', 'fila', 'humano']:
                print(f"🤖 Status: {status_conversa}. NUBIA ficará em silêncio.")
                return {"ok": True, "obs": "Atendimento humano em progresso"}
        else:
            print("Aviso: Falha ao checar status. Assumindo 'robo'.")
            
    except Exception as e:
        print(f"Erro ao checar status: {e}. Assumindo 'robo'.")

    # 3. Prepara Sessão e IA
    if id_para_responder not in user_sessions:
        user_sessions[id_para_responder] = {
            "menu_atual": None,
            "opcoes_validas": {},
            "chat_state": "IDLE", 
            "chat_pending_data": {},
            "api_nuvem": URL_NUVEM, 
            "nubia_vetores": GLOBAL_BRAIN.get("cerebro", {}),
            "nubia_cerebro": GLOBAL_BRAIN.get("cerebro", {}),
            "nubia_topicos": GLOBAL_BRAIN.get("topicos", []),
            "failure_count": 0 
        }
    else:
        sess = user_sessions[id_para_responder]
        if not sess.get("nubia_vetores") and GLOBAL_BRAIN.get("cerebro"):
            sess["nubia_vetores"] = GLOBAL_BRAIN.get("cerebro")
            sess["nubia_cerebro"] = GLOBAL_BRAIN.get("cerebro")
        if not sess.get("nubia_topicos") and GLOBAL_BRAIN.get("topicos"):
            sess["nubia_topicos"] = GLOBAL_BRAIN.get("topicos")

    # 4. Chama o Cérebro (Core)
    resposta_dict = {}
    try:
        resposta_dict = processar_mensagem(
            {"telefone": id_para_responder, "nome": dados.nome}, 
            dados.mensagem, 
            user_sessions[id_para_responder]
        )
    except Exception as e:
        print(f"Erro ao processar mensagem: {e}")
        resposta_dict = {"texto": "Desculpe, ocorreu um erro interno. Tente novamente ou digite 'menu' para voltar.", "tipo": "erro"}

    # 5. Envia a Resposta
    if resposta_dict and "texto" in resposta_dict:
        texto_resposta = resposta_dict["texto"]

        # Envia para o Node.js Local (Texto)
        try:
            payload_envio = {
                "telefone": id_para_responder, 
                "texto": texto_resposta, 
                "is_group": False
            }
            requests.post(f"{URL_BOT_LOCAL}/enviar", json=payload_envio)
            
        except Exception as e:
            print(f"Erro ao enviar resposta local: {e}")
        
        # Sincroniza o Log de envio na Nuvem
        try:
            requests.post(f"{URL_NUVEM}/sync/mensagem", json={
                "telefone": id_para_responder, "nome": dados.nome, 
                "texto": texto_resposta, 
                "remetente": "nubia", "status_envio": "enviado"
            }, verify=False)
        except Exception as e:
            print(f"Erro sync nuvem (Resposta): {e}")

    return {"ok": True}

# --- 2. RECEBE LISTA DE GRUPOS ---
@app.post("/sync/listas_local")
def sync_listas(listas: List[ListaZap]):
    print(f"🔄 Sincronizando {len(listas)} grupos com a nuvem...")
    try:
        requests.post(f"{URL_NUVEM}/sync/listas", json=[l.model_dump() for l in listas], verify=False)
    except Exception as e:
        print(f"Erro ao enviar listas pra nuvem: {e}")
    return {"ok": True}

# --- 3. O CARTEIRO ---
def loop_sincronizacao():
    print("📬 Carteiro iniciado...")
    while True:
        try:
            res = requests.get(f"{URL_NUVEM}/sync/fila_pendente", verify=False)
            
            if res.status_code == 200:
                msgs = res.json()
                for msg in msgs:
                    print(f"📤 Processando msg {msg['id']} para: {msg['telefone']}")
                    
                    try:
                        payload_bot = {}
                        endpoint_bot = "/enviar" 

                        base64_content = msg.get('arquivo_base64') or msg.get('base64')
                        
                        if base64_content:
                            print("   📎 Detectado anexo de mídia!")
                            # Verifica o tipo de arquivo/imagem/audio
                            payload_bot = {
                                "number": msg['telefone'],
                                "base64": base64_content,
                                "filename": msg.get('arquivo_nome', 'arquivo'),
                                "caption": msg.get('texto', '').split('] ')[-1] if ']' in msg.get('texto', '') else msg.get('texto', '')
                            }
                            
                            tipo = msg.get('arquivo_tipo', 'arquivo')
                            if tipo == 'imagem':
                                endpoint_bot = "/enviar_imagem"
                            elif tipo == 'audio':
                                endpoint_bot = "/enviar_audio"
                            else:
                                endpoint_bot = "/enviar_arquivo"
                                
                        else:
                            payload_bot = {
                                "telefone": msg['telefone'], 
                                "texto": msg['texto'],
                                "is_group": "@g.us" in msg['telefone']
                            }
                            endpoint_bot = "/enviar"

                        # Envia para o Bot Local
                        r_bot = requests.post(f"{URL_BOT_LOCAL}{endpoint_bot}", json=payload_bot)
                        
                        if r_bot.status_code == 200:
                            requests.post(f"{URL_NUVEM}/sync/confirmar/{msg['id']}", verify=False)
                            print("   ✅ Entregue ao Bot Local.")
                        else:
                            print(f"   ❌ Bot Local recusou: {r_bot.text}")
                        
                    except Exception as env_err:
                        print(f"   ❌ Erro local: {env_err}")
                        
        except Exception as e:
            pass 
        time.sleep(3)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)