import os
from typing import List, Optional
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client

app = FastAPI(title="NUBIA Cloud Bridge")

# ----------------------------
# CONFIGURAÇÃO SUPABASE
# ----------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️ AVISO: SUPABASE_URL ou SUPABASE_KEY não configurados.")
    supabase: Optional[Client] = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ----------------------------
# MODELS
# ----------------------------
class MsgSync(BaseModel):
    telefone: str
    nome: str = "Desconhecido"
    texto: str
    remetente: str
    status_envio: str = "enviado"
    arquivo_base64: Optional[str] = None
    arquivo_nome: Optional[str] = None
    arquivo_tipo: Optional[str] = None

class ListaZap(BaseModel):
    id: str
    nome: str
    qtd: int

class NovaConversa(BaseModel):
    telefone: str
    nome: str

class EnvioLista(BaseModel):
    lista_id: str
    mensagem: str
    atendente_nome: str
    base64: Optional[str] = None
    nome_arquivo: Optional[str] = None
    tipo_midia: Optional[str] = None
    
class TransferenciaSync(BaseModel):
    telefone: str
    setor: str

class WebhookLocal(BaseModel):
    telefone: str
    nome: str
    mensagem: str
    is_group: bool
    original_id: str

class EnviarImagem(BaseModel):
    number: str
    base64: str
    filename: str
    caption: Optional[str] = ""

class EnviarAudio(BaseModel):
    number: str
    base64: str

class EnviarArquivo(BaseModel):
    number: str
    base64: str
    filename: str
    caption: Optional[str] = ""


# ----------------------------
# HELPERS
# ----------------------------
def require_supabase():
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase não configurado.")

def now_iso():
    return datetime.now().isoformat()

def store_message(payload: dict):
    require_supabase()
    supabase.table("mensagens").insert(payload).execute()

def upsert_conversa(payload: dict):
    require_supabase()
    supabase.table("conversas").upsert(payload).execute()


# ----------------------------
# 1) ROTAS QUE O BOT LOCAL USA
# ----------------------------
def garantir_conversa_existente(telefone: str):
    require_supabase()
    res = supabase.table("conversas").select("telefone").eq("telefone", telefone).execute()
    
    if res.data:
        supabase.table("conversas").update({
            "ultima_interacao": now_iso()
        }).eq("telefone", telefone).execute()
    else:

        supabase.table("conversas").insert({
            "telefone": telefone,
            "nome_usuario": "Cliente (via Anexo)",
            "status": "atendimento",
            "ultima_interacao": now_iso()
        }).execute()

@app.post("/webhook/local")
def receber_do_zap_local(dados: WebhookLocal):
    require_supabase()
    tel = dados.telefone
    
    try:
        upsert_conversa({
            "telefone": tel,
            "nome_usuario": dados.nome,
            "ultima_mensagem_texto": dados.mensagem,
            "ultima_interacao": now_iso(),
            "status": "robo"
        })

        store_message({
            "telefone": tel,
            "remetente": "usuario",
            "texto": dados.mensagem,
            "status_envio": "recebido",
            "created_at": now_iso()
        })
        return {"ok": True}
    except Exception as e:
        print(f"ERRO WEBHOOK LOCAL: {e}")
        return {"ok": False, "error": str(e)}

@app.post("/sync/listas_local")
def salvar_grupos_local(grupos: List[ListaZap]):
    require_supabase()
    if not grupos: return {"ok": True}
    
    try:
        dados = [{
            "id": g.id, "nome": g.nome, "qtd": g.qtd, "updated_at": now_iso()
        } for g in grupos]
        supabase.table("listas_transmissao").upsert(dados).execute()
        return {"ok": True}
    except Exception as e:
        print(f"ERRO SYNC LISTAS: {e}")
        return {"ok": False, "error": str(e)}

@app.post("/sync/transferir")
def transferir_pelo_robo(dados: TransferenciaSync):
    require_supabase()
    try:
        supabase.table("conversas").update({
            "status": "fila",
            "setor_responsavel": dados.setor,
            "atendente_atual": None,
            "ultima_interacao": now_iso()
        }).eq("telefone", dados.telefone).execute()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/fila_setor/{setor}")
def fila_setor(setor: str):
    try:
        res = supabase.table("conversas")\
            .select("telefone", count="exact")\
            .eq("status", "fila")\
            .eq("setor_responsavel", setor)\
            .execute()
        return {"em_fila": res.count or 0}
    except:
        return {"em_fila": 0}

# ----------------------------
# 2) ROTAS DE MÍDIA
# ----------------------------
@app.post("/enviar_imagem")
def enviar_imagem(dados: EnviarImagem):
    require_supabase()
    try:
        clean = dados.base64
        if "," in clean and clean.startswith("data:"):
            clean = clean.split(",", 1)[1]

        garantir_conversa_existente(dados.number)

        store_message({
            "telefone": dados.number,
            "remetente": "atendente",
            "texto": f"[imagem:{dados.filename}] {dados.caption or ''}",
            "arquivo_nome": dados.filename,
            "arquivo_tipo": "imagem",
            "arquivo_base64": clean,
            "status_envio": "pendente",
            "created_at": now_iso()
        })
        return {"ok": True}
    except Exception as e:
        print(f"❌ ERRO IMAGEM: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/enviar_audio")
def enviar_audio(dados: EnviarAudio):
    require_supabase()
    try:
        clean = dados.base64
        if "," in clean and clean.startswith("data:"):
            clean = clean.split(",", 1)[1]

        garantir_conversa_existente(dados.number)

        store_message({
            "telefone": dados.number,
            "remetente": "atendente",
            "texto": "[audio]",
            "arquivo_nome": "audio.mp3",
            "arquivo_tipo": "audio", 
            "arquivo_base64": clean,
            "status_envio": "pendente",
            "created_at": now_iso()
        })
        return {"ok": True}
    except Exception as e:
        print(f"❌ ERRO AO SALVAR AUDIO: {e}")
        raise HTTPException(status_code=500, detail=f"Erro Banco de Dados: {str(e)}")


@app.post("/enviar_arquivo")
def enviar_arquivo(dados: EnviarArquivo):
    require_supabase()
    try:
        clean = dados.base64
        if "," in clean and clean.startswith("data:"):
            clean = clean.split(",", 1)[1]

        garantir_conversa_existente(dados.number)

        store_message({
            "telefone": dados.number,
            "remetente": "atendente",
            "texto": f"[arquivo:{dados.filename}] {dados.caption or ''}",
            "arquivo_nome": dados.filename,
            "arquivo_tipo": "documento",
            "arquivo_base64": clean,
            "status_envio": "pendente",
            "created_at": now_iso()
        })
        return {"ok": True}
    except Exception as e:
        print(f"❌ ERRO AO SALVAR ARQUIVO: {e}")
        raise HTTPException(status_code=500, detail=f"Erro Banco de Dados: {str(e)}")

# ----------------------------
# 3) ROTAS DE SINCRONIZAÇÃO (PC LOCAL -> NUVEM)
# ----------------------------
@app.post("/sync/mensagem")
def salvar_mensagem_do_local(dados: MsgSync):
    require_supabase()
    try:
        upsert_conversa({
            "telefone": dados.telefone,
            "nome_usuario": dados.nome,
            "ultima_mensagem_texto": dados.texto,
            "ultima_interacao": now_iso()
        })

        payload_msg = {
            "telefone": dados.telefone,
            "remetente": dados.remetente,
            "texto": dados.texto,
            "status_envio": dados.status_envio,
            "created_at": now_iso(),
            "arquivo_base64": dados.arquivo_base64,
            "arquivo_nome": dados.arquivo_nome,
            "arquivo_tipo": dados.arquivo_tipo
        }

        store_message(payload_msg)
        return {"ok": True}
    except Exception as e:
        print(f"ERRO SYNC MSG: {e}")
        return {"ok": False, "error": str(e)}

@app.post("/sync/listas")
def salvar_listas_do_zap(listas: List[ListaZap]):
    require_supabase()
    if not listas: return {"ok": True}
    try:
        dados = [{"id": l.id, "nome": l.nome, "qtd": l.qtd, "updated_at": now_iso()} for l in listas]
        supabase.table("listas_transmissao").upsert(dados).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/sync/fila_pendente")
def pegar_fila_para_local():
    require_supabase()
    try:
        res = supabase.table("mensagens").select("*").eq("status_envio", "pendente").execute()
        return res.data
    except Exception as e:
        print(f"ERRO AO PEGAR FILA: {e}")
        return []

@app.post("/sync/confirmar/{id_msg}")
def confirmar_envio_local(id_msg: int):
    require_supabase()
    try:
        supabase.table("mensagens").update({"status_envio": "enviado"}).eq("id", id_msg).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/sync/status_conversa/{telefone}")
def verificar_status(telefone: str):
    require_supabase()
    try:
        res = supabase.table("conversas").select("status, setor_responsavel").eq("telefone", telefone).execute()
        if res.data:
            return res.data[0]
        return {"status": "robo", "setor_responsavel": "geral"}
    except:
        return {"status": "robo", "setor_responsavel": "geral"}

# ----------------------------
# 4) ROTAS DO FLET
# ----------------------------
@app.get("/admin/conversas")
def listar_conversas(setor: Optional[str] = None):
    require_supabase()
    try:
        query = supabase.table("conversas").select("*").order("ultima_interacao", desc=True)
        if setor and setor != "GERAL":
            query = query.eq("setor_responsavel", setor)
        return query.execute().data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/chat/{telefone}")
def pegar_historico(telefone: str):
    require_supabase()
    try:
        res = supabase.table("mensagens")\
            .select("*")\
            .eq("telefone", telefone)\
            .order("created_at", desc=True)\
            .limit(50)\
            .execute()
        
        if not res.data:
            return []

        return res.data[::-1]
    except Exception as e:
        print(f"Erro ao pegar histórico: {e}")
        return []

@app.post("/admin/enviar")
def flet_enviar_mensagem(dados: MsgSync):
    require_supabase()
    try:
        texto_final = dados.texto
        if dados.remetente == "atendente":
            texto_final = f"*{dados.nome.strip()}:* {dados.texto}"

        store_message({
            "telefone": dados.telefone,
            "remetente": "atendente",
            "texto": texto_final,
            "status_envio": "pendente",
            "created_at": now_iso()
        })

        supabase.table("conversas").update({
            "ultima_mensagem_texto": f"Você: {dados.texto}",
            "ultima_interacao": now_iso()
        }).eq("telefone", dados.telefone).execute()
        
        return {"ok": True}
    except Exception as e:
        print(f"ERRO AO ENVIAR TEXTO: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/enviar_broadcast_lista")
def enviar_para_lista(dados: EnvioLista):
    require_supabase()
    try:

        garantir_conversa_existente(dados.lista_id) 

        clean_b64 = None
        if dados.base64:
            clean_b64 = dados.base64
            if "," in clean_b64 and clean_b64.startswith("data:"):
                clean_b64 = clean_b64.split(",", 1)[1]

        texto_base = f"📢 *Comunicado ({dados.atendente_nome}):*\n\n{dados.mensagem}"
        texto_final = texto_base

        if dados.tipo_midia == 'imagem':
            texto_final = f"[imagem:{dados.nome_arquivo or 'imagem.jpg'}] {texto_base}"
        elif dados.tipo_midia == 'audio':
            texto_final = "[audio]" 
        elif dados.tipo_midia == 'documento':
            texto_final = f"[arquivo:{dados.nome_arquivo or 'doc.bin'}] {texto_base}"

        store_message({
            "telefone": dados.lista_id,
            "remetente": "atendente",
            "texto": texto_final,
            "status_envio": "pendente",
            "created_at": now_iso(),
            "arquivo_base64": clean_b64,
            "arquivo_nome": dados.nome_arquivo,
            "arquivo_tipo": dados.tipo_midia
        })
        
        return {"ok": True}
    except Exception as e:
        print(f"❌ ERRO BROADCAST: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/assumir")
def assumir_conversa(telefone: str, atendente: str):
    require_supabase()
    try:
        supabase.table("conversas").update({
            "status": "atendimento",
            "atendente_atual": atendente
        }).eq("telefone", telefone).execute()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/encerrar")
def encerrar_conversa(telefone: str):
    require_supabase()
    try:
        supabase.table("conversas").update({
            "status": "robo",
            "atendente_atual": None,
            "setor_responsavel": "geral"
        }).eq("telefone", telefone).execute()

        store_message({
            "telefone": telefone,
            "remetente": "sistema",
            "texto": "Atendimento encerrado. NUBIA retornou.",
            "status_envio": "pendente",
            "created_at": now_iso()
        })
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/criar_conversa")
def criar_conversa_manual(dados: NovaConversa):
    require_supabase()
    try:
        tel = "".join(filter(str.isdigit, dados.telefone))
        tel_formatado = f"{tel}@c.us" if "@" not in dados.telefone else dados.telefone

        upsert_conversa({
            "telefone": tel_formatado,
            "nome_usuario": dados.nome,
            "status": "humano",
            "ultima_mensagem_texto": "Novo atendimento iniciado pelo Flet",
            "ultima_interacao": now_iso()
        })
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/listas_disponiveis")
def get_listas():
    require_supabase()
    return supabase.table("listas_transmissao").select("*").execute().data

@app.get("/health")
def health():
    return {"status": "ok"}