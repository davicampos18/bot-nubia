import os
import pickle
import torch
import gspread
import time
import uuid
from typing import Optional, Tuple, Any
from google.oauth2.service_account import Credentials
from sentence_transformers import SentenceTransformer, util
from config import NUBIA_CREDENTIALS, API_OPENAI
from datetime import datetime
from gtts import gTTS
from openai import OpenAI
import re


CLASSIFY_MODEL = "gpt-4o-mini"
PRIVACY_MODEL  = "gpt-4o-mini"
VERIFY_MODEL   = "gpt-4o-mini"


HUMANIZE_MODEL = "gpt-4o"
EXPAND_MODEL   = "gpt-4o"

# Vetores/cache
MASTER_SPREADSHEET_NAME = "NUBIA"
CACHE_VETORES = "cache_vetores.pkl"


client = OpenAI(api_key=API_OPENAI)


modelo_sentenca = None

# ---------------------
# Utils: OPENAI wrapper
# ---------------------
def consultar_openai(model: str,
                     prompt: str,
                     temperature: float = 0.0,
                     max_tokens: int = 1024,
                     system_msg: str = "Você é um assistente útil.") -> Optional[str]:
    """
    Chama a OpenAI com sistema de RETRY automático.
    """
    max_retries = 3
    delay_base = 5

    for tentativa in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            return response.choices[0].message.content.strip()

        except Exception as e:
            erro_str = str(e)
            print(f"⚠️ Erro OpenAI (tentativa {tentativa+1}): {e}")
            if "RateLimitError" in erro_str or "429" in erro_str:
                time.sleep(delay_base)
                delay_base *= 2
            else:
                return None
    
    print("❌ Falha na OpenAI após todas as tentativas.")
    return None

# ---------------------
# Mapa de navegação (menu)
# ---------------------
MAPA_NUBIA = {
    "Autorizações Médicas (SERAMO)": {
        "tipo": "submenu",
        "opcoes": {
            "Consultas e Exames": "Como solicitar autorização para consultas e exames médicos?",
            "Tratamentos Seriados (Fisio/Psico/Fono)": "Quais as regras e prazos para tratamentos seriados como fisioterapia e psicologia?",
            "Cirurgias e Internações": "Como solicitar autorização para cirurgias e internações?",
            "Home Care": "Como funciona e como solicitar o serviço de Home Care?",
            "TFD (Tratamento Fora de Domicílio)": "Como solicitar Tratamento Fora de Domicílio (TFD)?",
            "Voltar ao Início": "MENU_INICIAL"
        }
    },
    "Odontologia (SERAMO Odonto)": {
        "tipo": "submenu",
        "opcoes": {
            "Autorização de Tratamento": "Como solicitar autorização para tratamento odontológico?",
            "Reembolso Odontológico": "Como solicitar reembolso de despesas odontológicas?",
            "Ortodontia (Aparelho)": "Quais as regras e perícias para uso de aparelho ortodôntico?",
            "Perícias Odontológicas": "Como e onde realizar a perícia odontológica?",
            "Voltar ao Início": "MENU_INICIAL"
        }
    },
    "Saúde Ocupacional e Atestados (SERSAO)": {
        "tipo": "submenu",
        "opcoes": {
            "Enviar/Homologar Atestado": "Como faço para enviar e homologar meu atestado médico?",
            "Prorrogação de Afastamento": "Como solicitar prorrogação do afastamento médico?",
            "Junta Médica": "Quando é necessário passar por junta médica?",
            "Exames Periódicos (EPS)": "Como realizar os exames periódicos de saúde (EPS)?",
            "Teletrabalho e ASO": "Como emitir o ASO para teletrabalho?",
            "Voltar ao Início": "MENU_INICIAL"
        }
    },
    "Cadastro e Benefícios (SEABE)": {
        "tipo": "submenu",
        "opcoes": {
            "Inclusão de Dependentes": "Como faço para incluir dependentes no Pro-Social?",
            "Carteirinha Digital": "Como obter a carteirinha digital do plano?",
            "Auxílio-Natalidade": "Como solicitar o auxílio-natalidade?",
            "Auxílio-Pré-Escolar": "Como solicitar o auxílio pré-escolar?",
            "Coparticipação": "Como funciona a coparticipação no Pro-Social?",
            "Voltar ao Início": "MENU_INICIAL"
        }
    },
    "Financeiro e Reembolsos (SEFAT)": {
        "tipo": "submenu",
        "opcoes": {
            "Reembolso Médico/OPME": "Como solicitar reembolso de despesas médicas e OPME?",
            "Glosa e Faturamento": "Como verificar glosas e faturas?",
            "Demonstrativo/Pagamentos": "Como consultar pagamentos e demonstrativos?",
            "Voltar ao Início": "MENU_INICIAL"
        }
    },
    "Rede Credenciada (SERCRE)": {
        "tipo": "submenu",
        "opcoes": {
            "Consultar Rede": "Como consultar a rede credenciada de médicos e clínicas?",
            "Credenciamento de Prestador": "Como um médico ou clínica pode se credenciar ao Pro-Social?",
            "Voltar ao Início": "MENU_INICIAL"
        }
    },
    "Bem-Estar e Apoio (NUBES/SESAI)": {
        "tipo": "submenu",
        "opcoes": {
            "Programas de Bem-Estar": "Quais são os programas de bem-estar e qualidade de vida do NUBES?",
            "Acolhimento Psicossocial": "Como solicitar apoio psicossocial ou acolhimento?",
            "Casos Complexos de Saúde": "Como a SESAI atua em casos complexos de saúde?",
            "Voltar ao Início": "MENU_INICIAL"
        }
    },
    "Outros Assuntos / Digitar Livremente": {
        "tipo": "acao_livre",
        "texto": ""
    }
}

def get_mapa_nubia():
    return MAPA_NUBIA

def formatar_texto_menu(chave_menu):
    """
    Gera o texto do menu e o dicionário de opções válidas.
    Retorna: (texto, opcoes_validas)
    """
    mapa = get_mapa_nubia()
    texto = ""
    opcoes_validas = {}

    if chave_menu == "MENU_INICIAL":
        texto = "*Olá! Sou a NUBIA. Como posso ajudar?* 👇\n\n"
        for i, chave in enumerate(mapa.keys(), 1):
            texto += f"*{i}.* {chave}\n"
            opcoes_validas[str(i)] = chave
        texto += "\n_(Digite o número da opção)_"
    elif chave_menu in mapa:
        dados = mapa[chave_menu]
        if dados["tipo"] == "submenu":
            texto = f"*{chave_menu}* 👇\n\n"
            for i, (label, pergunta_real) in enumerate(dados["opcoes"].items(), 1):
                texto += f"*{i}.* {label}\n"

                opcoes_validas[str(i)] = label 
                
            texto += "\n_(Digite o número da opção)_"
        elif dados["tipo"] == "acao_livre":
            texto = "Entendido! Pode digitar sua dúvida livremente abaixo: 👇"
            opcoes_validas = "LIVRE"
    return texto, opcoes_validas

def gerar_audio_resposta(texto: str) -> Optional[str]:
    try:
        if not texto: return None
        texto_limpo = texto.replace("*", "").replace("#", "")
        tts = gTTS(text=texto_limpo, lang='pt', tld='com.br')
        pasta_destino = os.path.abspath("assets/audios")
        if not os.path.exists(pasta_destino): os.makedirs(pasta_destino)
        nome_arquivo = f"nubia_{uuid.uuid4()}.mp3"
        caminho_completo = os.path.join(pasta_destino, nome_arquivo)
        tts.save(caminho_completo)
        return caminho_completo
    except Exception as e:
        print(f"⚠️ Erro áudio: {e}")
        return None

# ---------------------
# Embeddings & Vetorização - (SentenceTransformer não depende da OpenAI)
# ---------------------
def get_modelo_sentenca():
    global modelo_sentenca
    if modelo_sentenca is None:
        print("🔹 Carregando modelo de embeddings (SentenceTransformer)...")
        modelo_sentenca = SentenceTransformer('sentence-transformers/paraphrase-multilingual-mpnet-base-v2')
    return modelo_sentenca

def conectar_sheets(aba: str):
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_file(NUBIA_CREDENTIALS, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open(MASTER_SPREADSHEET_NAME).worksheet(aba)

def carregar_base_conhecimento():
    return conectar_sheets("perguntas").get_all_records()

def vetorizar_base_conhecimento(force_reload: bool = False) -> Tuple[dict, list]:
    """
    Vetoriza a base e salva em cache.
    BLINDAGEM: Remove espaços em branco dos tópicos para garantir match exato com o menu.
    """
    if os.path.exists(CACHE_VETORES) and not force_reload:
        try:
            print("💾 Tentando carregar cache de vetores...")
            with open(CACHE_VETORES, "rb") as f:
                dados = pickle.load(f)
                if isinstance(dados, tuple) and len(dados) == 2:
                    return dados[0], dados[1]
                else:
                    print("⚠️ Cache inválido. Recalculando...")
        except Exception as e:
            print(f"⚠️ Falha ao ler cache ({e}). Recalculando...")

    print("🧠 Recalculando vetores (Limpando sujeira dos dados)...")
    modelo_ia = get_modelo_sentenca()
    base = carregar_base_conhecimento()
    cerebro = {}

    topicos_sujos = set(l.get("topico", "Outros Assuntos") for l in base)
    topicos_limpos = sorted(list(set([str(t).strip() for t in topicos_sujos if t])))
    
    if "Outros Assuntos" not in topicos_limpos:
        topicos_limpos.append("Outros Assuntos")

    print(f"📋 Tópicos encontrados na Planilha: {topicos_limpos}")

    for topico in topicos_limpos:

        linhas = [
            l for l in base 
            if str(l.get("topico", "Outros Assuntos")).strip() == topico
        ]
        
        if not linhas:
            continue
            
        docs = [f"{l['Pergunta_Chave']} " * 5 + f"{l['Resposta_Crua']}" for l in linhas]
        vetores = modelo_ia.encode(docs, convert_to_tensor=True)
        
        cerebro[topico] = {"vetores": vetores, "linhas": linhas}

    try:
        with open(CACHE_VETORES, "wb") as f:
            pickle.dump((cerebro, topicos_limpos), f)
            print("💾 Novo cache limpo e salvo!")
    except Exception as e:
        print(f"[WARN] Erro ao salvar cache: {e}")

    return cerebro, topicos_limpos

# ---------------------
# Busca (vetorial)
# ---------------------
def encontrar_resposta_correspondente(pergunta: str, topico_sugerido: str, cerebro: dict) -> Optional[dict]:
    modelo = get_modelo_sentenca()

    def buscar_em_um_topico(nome_topico: str):
        nome_limpo = nome_topico.strip()
        if nome_limpo not in cerebro: return None, 0.0
            
        dados = cerebro[nome_limpo]
        vetor_usuario = modelo.encode([pergunta], convert_to_tensor=True)
        similaridades = util.pytorch_cos_sim(vetor_usuario, dados["vetores"])[0]
        
        siglas = ["SERCRE", "SESAI", "SEABE", "SERSAO", "SERAMO", "NUBES", "NUTRIÇÃO", "ODONTO", "ATESTADO", "HOMOLOGAR"]
        p_upper = pergunta.upper()
        for i, linha in enumerate(dados["linhas"]):
            conteudo = (str(linha.get('Pergunta_Chave','')) + " " + str(linha.get('Resposta_Crua',''))).upper()
            for s in siglas:
                if s in p_upper and s in conteudo: similaridades[i] += 0.25
                    
        melhor_score = torch.max(similaridades).item()
        idx = torch.argmax(similaridades).item()
        return dados["linhas"][idx], melhor_score

    print(f"🔍 Buscando em: '{topico_sugerido}'")
    resultado, score = buscar_em_um_topico(topico_sugerido)
    
    if score >= 0.65: 
        print(f"🎯 Alvo Forte encontrado! Score: {score:.3f}")
        resultado["_score"] = score
        return resultado
    

    if score >= 0.35:
        print(f"⚠️ Alvo Médio encontrado. Score: {score:.3f}")
        resultado["_score"] = score
        return resultado

    print(f"⚠️ Nada bom em '{topico_sugerido}' (Score: {score:.3f}). Tentando vizinhos...")
    melhor_resultado_global = None
    melhor_score_global = 0.0
    
    for topico_atual in cerebro.keys():
        if topico_atual == topico_sugerido: continue
        res_temp, score_temp = buscar_em_um_topico(topico_atual)
        if score_temp > melhor_score_global:
            melhor_score_global = score_temp
            melhor_resultado_global = res_temp

    if melhor_score_global >= 0.40:
        print(f"🌍 Achado em '{melhor_resultado_global.get('topico')}'. Score: {melhor_score_global:.3f}")
        melhor_resultado_global["_score"] = melhor_score_global
        return melhor_resultado_global
        
    return None

# ---------------------
# FUNÇÕES DE LLM (HUMANIZAÇÃO, PRIVACIDADE, CLASSIFICAÇÃO DE TÓPICO, VERIFICAR RESPOSTA E EXPLICAÇÃO DA RESPOSTA)
# ---------------------
def humanizar_resposta_com_ia(dado: dict, pergunta_usuario: str) -> str:
    resposta_crua = dado.get("Resposta_Crua", "")
    setor = dado.get("Setor_Responsavel", "")
    base_legal = dado.get("base_legal", "")
    

    texto_setor = ""
    if setor and setor not in ["NUBES", "Setor Responsável", ""]:
        texto_setor = f"\n\nPara mais orientações, a equipe do *{setor}* está à disposição."

    print(f"\n📝 [HUMANIZER INPUT] Base de Dados entregou: '{resposta_crua}'")

    prompt = f"""
Atue como um Formatador de Texto Estrito.
Sua missão é reescrever a "RESPOSTA TÉCNICA" abaixo para torná-la amigável ao usuário.

⚠️ REGRAS DE OURO (Siga rigorosamente):
1. USE APENAS AS INFORMAÇÕES DA "RESPOSTA TÉCNICA".
2. NÃO adicione procedimentos externos (como "procure o RH") se não estiver escrito no texto.
3. NÃO invente passos que não existam na fonte.
4. Se a resposta técnica disser "Não é necessário", MANTENHA essa informação.

DADOS:
- Pergunta do Usuário: "{pergunta_usuario}"
- RESPOSTA TÉCNICA (Sua ÚNICA fonte de verdade): "{resposta_crua}"
- Base Legal: "{base_legal}"

Gere a resposta final amigável agora:
"""
    try:
        resp = consultar_openai(HUMANIZE_MODEL, prompt, system_msg="Você é um redator que obedece estritamente a fonte de dados.")
        
        return (resp + texto_setor) if resp else (resposta_crua + texto_setor)
        
    except Exception as e:
        print(f"⚠️ Erro na humanização: {e}")
        return resposta_crua + texto_setor

def verificar_privacidade(pergunta: str) -> str:
    prompt = f"""
Classifique como INSEGURO se a pergunta pedir dados pessoais de terceiros ou for ofensiva.
Classifique como SEGURO se for dúvida sobre regras, leis ou dados do próprio usuário.
Pergunta: "{pergunta}"
Responda APENAS: SEGURO ou INSEGURO.
"""
    resp = consultar_openai(PRIVACY_MODEL, prompt, max_tokens=10)
    if resp and "INSEGURO" in resp.upper(): return "INSEGURO"
    return "SEGURO"

def classificar_topico_inteligente(pergunta: str, lista_todos_topicos: list) -> str:
    """
    Recebe a pergunta e a lista de TODOS os tópicos do sistema.
    O GPT decide qual é o melhor encaixe, ignorando onde o usuário clicou.
    """
    lista_formatada = "\n".join([f"- {t}" for t in lista_todos_topicos if t != "Outros Assuntos"])
    
    prompt = f"""
Você é um triador especialista. O usuário fez uma pergunta, mas pode estar no menu errado.
Analise a pergunta e diga em qual desses Tópicos ela se encaixa melhor.

LISTA DE TÓPICOS VÁLIDOS:
{lista_formatada}
- Outros Assuntos

PERGUNTA DO USUÁRIO: "{pergunta}"

REGRA: Retorne APENAS o nome exato do tópico da lista acima. Sem explicações.
"""
    resp = consultar_openai("gpt-4o-mini", prompt, max_tokens=60, temperature=0.0)
    
    if not resp:
        return "Outros Assuntos"
        
    topico_sugerido = resp.strip().strip(".").strip('"')

    for t in lista_todos_topicos:
        if t.lower() == topico_sugerido.lower():
            return t
        if t.lower() in topico_sugerido.lower() and len(topico_sugerido) > 5:
            return t
            
    return "Outros Assuntos"

def verificar_resposta_sim_nao(pergunta: str, resposta: str) -> Optional[bool]:
    """
    Verifica se a resposta é pertinente.
    BLINDAGEM V2: Impede aprovação de respostas desconexas mesmo que tenham redirecionamento.
    """
    print(f"\n🧐 --- AUDITORIA IA ---")
    print(f"❓ Pergunta: {pergunta}")
    print(f"🗣️ Resposta Candidata: {resposta}")
    
    prompt = f"""
Atue como um analista de suporte sênior e cético.
Analise se a RESPOSTA abaixo serve de fato para a PERGUNTA do usuário.

PERGUNTA: "{pergunta}"
RESPOSTA: "{resposta}"

REGRAS DE JULGAMENTO:
1. Se a resposta falar sobre um ASSUNTO DIFERENTE da pergunta, o Veredito DEVE ser NÃO (mesmo que indique um setor).
   Exemplo de ERRO: Pergunta "Como autorizo?" vs Resposta "Isso não gera licença médica". -> VEREDITO: NÃO.

2. O redirecionamento para um setor (email/telefone) SÓ É VÁLIDO se o texto explicar que aquele assunto ESPECÍFICO exige contato humano.

3. Negativas ("não precisa", "não gera") só são válidas se responderem diretamente ao tema perguntado.

Responda no formato:
RACIOCINIO: [Breve explicação crítica]
VEREDITO: [SIM ou NÃO]
"""
    
    try:
        resp = consultar_openai(VERIFY_MODEL, prompt, max_tokens=100, temperature=0.0)
        
        if not resp: return None
            
        print(f"🤖 Análise do Modelo:\n{resp}\n----------------------")

        resp_upper = resp.upper()
        if "VEREDITO: SIM" in resp_upper: return True
        if "VEREDITO: NÃO" in resp_upper or "VEREDITO: NAO" in resp_upper: return False

        if "SIM" in resp_upper: return True
        return False

    except Exception as e:
        print(f"⚠️ Erro no validador: {e}")
        return None

def expandir_resposta_com_ia(dado: dict, pergunta_usuario: str) -> str:
    prompt = f"Explique melhor: Pergunta: {pergunta_usuario} | Info: {dado.get('Resposta_Crua','')}"
    resp = consultar_openai(EXPAND_MODEL, prompt)
    return resp if resp else dado.get("Resposta_Crua", "")

# ---------------------
# SEGURANÇA: SANITIZAÇÃO (REGEX)
# ---------------------
def mascarar_dados_sensiveis(texto: str) -> str:
    """
    Remove padrões de CPF, Matrícula e E-mails pessoais antes de enviar ao LLM.
    Defesa em profundidade.
    """
    texto_seguro = texto

    # 1. Mascarar CPF (com ou sem pontuação)
    padrao_cpf = r'\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b'
    texto_seguro = re.sub(padrao_cpf, "[CPF_REMOVIDO]", texto_seguro)

    # 2. Mascarar Matrícula
    padrao_matricula = r'\b\d{5,9}\b'
    texto_seguro = re.sub(padrao_matricula, "[MATRICULA_REMOVIDA]", texto_seguro)
    
    # 3. Mascarar E-mail
    padrao_email = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    texto_seguro = re.sub(padrao_email, "[EMAIL_REMOVIDO]", texto_seguro)

    return texto_seguro

# ---------------------
# LOGS 
# ---------------------
def logar_pergunta_nao_respondida(pergunta: str, nome_usuario: str):
    try:
        aba = conectar_sheets("nao_respondida")
        aba.append_row([str(datetime.now()), nome_usuario, pergunta, "NÃO RESPONDIDA"])
    except: pass

def consultar_gemini(prompt: str, sistema: Optional[str] = None, modelo: str = "gpt-4o") -> str:
    """
    Função de compatibilidade para o nubia_core.py não quebrar.
    Redireciona para consultar_openai.
    """
    sys_msg = sistema if sistema else "Você é um assistente útil."
    resp = consultar_openai(model=modelo, prompt=prompt, system_msg=sys_msg)
    return resp if resp else ""

def logar_nps(nota: int, comentario: str, telefone: str):
    """
    Salva a nota de satisfação (1-5) no Google Sheets.
    """
    print(f"[METRICA] ⭐ NPS Recebido: {nota} - Cliente: {telefone}")
    try:
        aba = conectar_sheets("nps") 
        aba.append_row([str(datetime.now()), telefone, nota, comentario])
    except Exception as e:
        print(f"⚠️ Erro ao salvar NPS no Sheets: {e}")