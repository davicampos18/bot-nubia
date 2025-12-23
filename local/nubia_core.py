from typing import Optional, Dict, Any
import requests
import traceback

from nubia_brain import (
    encontrar_resposta_correspondente,
    humanizar_resposta_com_ia,
    verificar_privacidade,
    classificar_topico_inteligente,
    get_mapa_nubia,
    formatar_texto_menu,
    gerar_audio_resposta,
    logar_pergunta_nao_respondida,
    get_modelo_sentenca,
    verificar_resposta_sim_nao,
    mascarar_dados_sensiveis,
    logar_nps,

)


from sentence_transformers import util as st_util

SIM_FALLBACK_APPROVE = 0.40
SIM_FALLBACK_RETRY = 0.25


def _is_reset_command(txt: str) -> bool:
    if not txt:
        return False
    t = txt.lower().strip()
    return t in ["oi", "ola", "olá", "menu", "inicio", "voltar", "sair"]

def _is_transfer_command(txt: str) -> bool:
    if not txt:
        return False
    t = txt.lower().strip()
    return t in ["transferir", "transfer", "atendente", "humano", "quero humano"]

def _is_affirmative(txt: str) -> bool:
    if not txt:
        return False
    return txt.lower().strip() in ["sim", "s", "yes", "y"]

def _is_negative(txt: str) -> bool:
    if not txt:
        return False
    return txt.lower().strip() in ["não", "nao", "n", "no"]

def _transfer_to_human(session: Dict[str, Any], usuario: Dict[str, Any], setor: str) -> bool:
    """
    Chama o endpoint /sync/transferir na nuvem usando session['api_nuvem'].
    Retorna True se a requisição aparentemente funcionou (status 200).
    """
    url_nuvem = session.get("api_nuvem")
    telefone = usuario.get("telefone", "")
    if not url_nuvem:
        print("[NUBIA] transfer: URL_NUVEM não encontrada na sessão.")
        return False
    try:
        resp = requests.post(
            f"{url_nuvem}/sync/transferir",
            json={"telefone": telefone, "setor": setor},
            timeout=10,
            verify=False
        )
        if resp.status_code == 200:
            print(f"[NUBIA] Transferência solicitada -> setor={setor}, telefone={telefone}")
            return True
        else:
            print(f"[NUBIA] Transferência retornou status {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        print(f"[NUBIA] Erro ao solicitar transferência: {e}")
        return False

def _close_after_transfer(session: Dict[str, Any], setor: str) -> Dict[str, Any]:
    tempo_estimado = _obter_estimativa_fila(session, setor)

    msg_transferencia = (
        f"Pronto! Você foi encaminhado para um atendente do setor *{setor}*.\n"
        f"👥 *Tempo estimado de espera:* {tempo_estimado}.\n\n"
        "Aguarde — o atendente do setor continuará daqui para frente."
    )

    preservar = {}
    if "nubia_vetores" in session: preservar["nubia_vetores"] = session["nubia_vetores"]
    if "nubia_topicos" in session: preservar["nubia_topicos"] = session["nubia_topicos"]
    if "api_nuvem" in session: preservar["api_nuvem"] = session["api_nuvem"]

    session.clear()
    session.update(preservar)

    return {"texto": msg_transferencia, "tipo": "resposta"}

def _obter_estimativa_fila(session: Dict[str, Any], setor: str) -> str:
    """
    Consulta a API da nuvem para ver quantas pessoas estão na fila desse setor
    e retorna uma string de tempo estimado.
    """
    url_nuvem = session.get("api_nuvem")
    if not url_nuvem: return "alguns minutos"
    
    try:
        sigla = setor
        if "(" in setor and ")" in setor:
            sigla = setor.split("(")[-1].replace(")", "")
            
        resp = requests.get(f"{url_nuvem}/admin/fila_setor/{sigla}", timeout=5, verify=False)
        
        if resp.status_code == 200:
            dados = resp.json()
            qtd = dados.get("em_fila", 0)
            
            if qtd <= 2:
                return "menos de 10 minutos"
            elif qtd <= 5:
                return "cerca de 15 a 30 minutos"
            else:
                return "mais de 45 minutos"
                
    except Exception as e:
        print(f"[WARN] Falha ao obter fila: {e}")
        
    return "alguns minutos"


def _llm_verify_answer(pergunta: str, resposta: str) -> Optional[bool]:
    """
    Wrapper que delega a verificação para o nubia_brain.
    Isso garante que usamos o prompt 'blindado' que aceita negativas informativas.
    """
    try:
        return verificar_resposta_sim_nao(pergunta, resposta)
    except Exception as e:
        print(f"[WARN] _llm_verify_answer falhou ao chamar o brain: {e}")
        return None

def _semantic_similarity_fallback(pergunta: str, resposta: str) -> float:
    """
    Calcula similaridade semântica via SentenceTransformer (fallback).
    Retorna score [0..1].
    """
    try:
        model = get_modelo_sentenca()
        vq = model.encode([pergunta], convert_to_tensor=True)
        va = model.encode([resposta], convert_to_tensor=True)
        sim = float(st_util.pytorch_cos_sim(vq, va)[0][0].item())
        return sim
    except Exception as e:
        print(f"[WARN] Falha fallback similarity: {e}")
        return 0.0

def processar_mensagem(usuario: Dict[str, Any], mensagem_usuario: str, session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Processa a mensagem com Lógica Híbrida (Duelo de Tópicos), Segurança e UX (NPS/Feedback).
    """
    if session is None: session = {}
    msg = (mensagem_usuario or "").strip()
    
    # --- SEGURANÇA: Sanitização ---
    # Mascara CPF/Matrícula antes de logs ou envio para IA
    msg_segura = mascarar_dados_sensiveis(msg)
    pergunta_usuario = msg_segura 

    # --- Fluxo de NPS (Pesquisa de Satisfação - Nota 1 a 5) ---
    if session.get("awaiting_nps"):
        nota = "".join(filter(str.isdigit, msg[:5]))
        
        if nota and 1 <= int(nota) <= 5:
            try:
                logar_nps(int(nota), msg, usuario.get("telefone", "anonimo"))
            except: pass
            
            preserved = {}
            for key in ["nubia_vetores", "nubia_topicos", "api_nuvem"]:
                if key in session: preserved[key] = session[key]
            session.clear()
            session.update(preserved)
            
            return {"texto": "Obrigada pela avaliação! ⭐\nFico feliz em ter ajudado. Até a próxima!", "tipo": "resposta"}
        else:
            return {"texto": "Por favor, digite apenas uma nota de *1 a 5*.", "tipo": "menu"}

    if session.get("awaiting_feedback"):
        escolha = msg.split()[0].lower().replace(".", "")
        
        # 1. Sim / Gostei -> Pede NPS
        if escolha in ["1", "sim", "s", "gostei"]:
            session.pop("awaiting_feedback", None)
            session["awaiting_nps"] = True
            return {"texto": "Que ótimo! 🤩\n\n*De 1 a 5, que nota você dá para o meu atendimento hoje?*", "tipo": "menu"}
            
        # 2. Não / Falar com Humano -> Transfere para Atendente
        elif escolha in ["2", "nao", "não", "n", "humano"]:
            contexto = session.get("contexto", {}) or {}
            setor = contexto.get("setor", "Atendimento Geral")
            _transfer_to_human(session, usuario, setor)
            return _close_after_transfer(session, setor)
            
        # 3. Outra Dúvida -> Volta ao Menu Inicial
        elif escolha in ["3", "outra", "menu"]:
            texto_menu, opcoes = formatar_texto_menu("MENU_INICIAL")
            session["menu_atual"] = "MENU_INICIAL"
            session["opcoes_validas"] = opcoes
            session.pop("awaiting_feedback", None)
            session.pop("contexto", None)
            session["contador_interacoes"] = 0
            return {"texto": texto_menu, "tipo": "menu"}
            
        else:
            return {"texto": "⚠️ Opção inválida.\nDigite *1* (Sim), *2* (Não/Humano) ou *3* (Outra Dúvida).", "tipo": "erro"}

    # --- Reset / Menu Inicial ---
    if _is_reset_command(msg) or not session.get("menu_atual"):
        texto_menu, opcoes = formatar_texto_menu("MENU_INICIAL")
        session["menu_atual"] = "MENU_INICIAL"
        session["opcoes_validas"] = opcoes
        session.pop("aguardando_pergunta", None)
        session.pop("contexto", None)
        session.pop("awaiting_feedback", None)
        session["contador_interacoes"] = 0
        return {"texto": texto_menu, "tipo": "menu"}

    # --- Respondendo Pergunta ---
    if session.get("aguardando_pergunta") or session.get("opcoes_validas") == "LIVRE":
        
        # Transferência manual
        if _is_transfer_command(msg):
            contexto = session.get("contexto", {}) or {}
            setor = contexto.get("setor", "Atendimento")
            _transfer_to_human(session, usuario, setor)
            return _close_after_transfer(session, setor)

        # Privacidade
        try:
            if verificar_privacidade(pergunta_usuario) == "INSEGURO":
                print(f"[METRICA] 🛡️ Bloqueio de Privacidade.")
                return {"texto": "Desculpe, sua pergunta parece conter dados sensíveis. Por segurança, reformule sem dados pessoais.", "tipo": "erro"}
        except: pass

        # Configuração do Contexto
        contexto = session.get("contexto", {}) or {}
        setor_usuario = contexto.get("setor")
        subtopico_usuario = contexto.get("subtopico")
        
        cerebro = session.get("nubia_vetores") or session.get("nubia_cerebro") or {}
        todos_topicos = session.get("nubia_topicos") or []
        if not todos_topicos and cerebro: todos_topicos = list(cerebro.keys())

        
        # Definir os competidores
        topico_usuario = (subtopico_usuario if subtopico_usuario else setor_usuario) or ""
        topico_usuario = topico_usuario.strip()
        
        # Palpite da IA (Global)
        topico_ia = "Outros Assuntos"
        try:
            topico_ia = classificar_topico_inteligente(pergunta_usuario, todos_topicos)
        except: pass

        print(f"🥊 DUELO: Usuário diz '{topico_usuario}' vs IA diz '{topico_ia}'")

        candidato_vencedor = None
        topico_vencedor = ""
        score_usuario = 0.0
        score_ia = 0.0

        # Busca no Tópico do Usuário (Se existir)
        res_usuario = None
        if topico_usuario:
            try:
                res_usuario = encontrar_resposta_correspondente(pergunta_usuario, topico_usuario, cerebro)
                if res_usuario: score_usuario = res_usuario.get("_score", 0.0)
            except: pass

        # Busca no Tópico da IA (Só se for diferente)
        res_ia = None
        if topico_ia and topico_ia != topico_usuario and topico_ia != "Outros Assuntos":
            try:
                res_ia = encontrar_resposta_correspondente(pergunta_usuario, topico_ia, cerebro)
                if res_ia: score_ia = res_ia.get("_score", 0.0)
            except: pass

        # Decidir o Tópico Vencedor
        print(f"📊 Scores -> Usuário: {score_usuario:.3f} | IA: {score_ia:.3f}")

        if score_ia > score_usuario: 
            candidato_vencedor = res_ia
            topico_vencedor = topico_ia
            print(f"🏆 Vitória da IA! Mudando tópico para '{topico_ia}'")
        elif res_usuario: 
            candidato_vencedor = res_usuario
            topico_vencedor = topico_usuario
            print(f"🏆 Vitória do Usuário (Mantendo tópico)")
        else:
            candidato_vencedor = res_ia
            topico_vencedor = topico_ia

        # ==========================================================
        # VALIDAÇÃO E ENTREGA
        # ==========================================================
        resposta_final_texto = None

        if candidato_vencedor:
            resp_humana = humanizar_resposta_com_ia(candidato_vencedor, pergunta_usuario)
            
            validacao = _llm_verify_answer(pergunta_usuario, resp_humana)
            
            if validacao is True:
                resposta_final_texto = resp_humana
            else:
                print(f"[METRICA] ❌ LLM rejeitou a resposta vencedora.")

        if resposta_final_texto:
            print(f"[METRICA] ✅ Resposta Entregue. Tópico Final: {topico_vencedor}")
            session["retry_count"] = 0
            
            contador = session.get("contador_interacoes", 0) + 1
            session["contador_interacoes"] = contador
            
            follow = ""
            if contador % 2 != 0:
                follow = (
                    "\n\n────────────────\n"
                    "🎯 *Essa resposta ajudou você?*\n\n"
                    "1️⃣ *Sim* (Avaliar)\n"
                    "2️⃣ *Não* (Falar com Humano)\n"
                    "3️⃣ *Outra Dúvida*"
                )
                session["awaiting_feedback"] = True
                session.pop("aguardando_pergunta", None)
                session.pop("contexto", None)
            else:
                follow = "\n_(Pode digitar outra dúvida se quiser)_"

            caminho_audio = None
            try: caminho_audio = gerar_audio_resposta(resposta_final_texto)
            except: pass
            
            return {"texto": resposta_final_texto + follow, "audio": caminho_audio, "tipo": "resposta"}

        else:
            # [FALHA] - Chance de Reformulação da Pergunta
            print(f"[METRICA] ⚠️ Não encontrado/Rejeitado. Pedindo reformulação.")
            
            # Checa se é a primeira vez falhando nessa interação
            tentativas = session.get("retry_count", 0)
            
            if tentativas < 1:
                session["retry_count"] = tentativas + 1
                msg_erro = (
                    "🤔 Hum, não encontrei uma resposta exata para isso na gaveta que procuramos.\n"
                    "Poderia tentar *reformular sua pergunta* com outras palavras?\n\n"
                    "_(Ou digite 'transferir' para falar com um atendente)_"
                )
                return {"texto": msg_erro, "tipo": "erro"}
            else:
                session["retry_count"] = 0 
                msg_final = (
                    "É, realmente não estou conseguindo achar essa informação na minha base. 😕\n"
                    "Para não te deixar esperando, acho melhor chamar um especialista.\n\n"
                    "1️⃣ *Transferir para Humano*\n"
                    "3️⃣ *Voltar ao Menu*"
                )
                session["awaiting_feedback"] = True 

                return {"texto": msg_final, "tipo": "menu"}

    # --- Navegação de Menu ---
    menu_atual = session.get("menu_atual")
    opcoes_validas = session.get("opcoes_validas")

    if menu_atual and opcoes_validas and opcoes_validas != "LIVRE":
        escolha = msg.split()[0].replace(".", "")
        if escolha in opcoes_validas:
            destino = opcoes_validas[escolha]

            if destino == "MENU_INICIAL":
                texto, opcoes = formatar_texto_menu("MENU_INICIAL")
                session["menu_atual"] = "MENU_INICIAL"
                session["opcoes_validas"] = opcoes
                session.pop("aguardando_pergunta", None)
                session.pop("contexto", None)
                session["contador_interacoes"] = 0
                return {"texto": texto, "tipo": "menu"}

            mapa = get_mapa_nubia()
            if destino in mapa:
                texto, opcoes = formatar_texto_menu(destino)
                novo_modo = "LIVRE" if opcoes == "LIVRE" else destino
                session["menu_atual"] = novo_modo
                session["opcoes_validas"] = opcoes
                session.pop("aguardando_pergunta", None)
                session.pop("contexto", None)
                return {"texto": texto, "tipo": "menu"}

            subtopico_escolhido = destino
            setor_atual = menu_atual
            session["aguardando_pergunta"] = True
            session["contexto"] = {"setor": setor_atual, "subtopico": subtopico_escolhido}
            session["contador_interacoes"] = 0 
            prompt = (
                f"Certo! Sobre *{subtopico_escolhido}*, qual é a sua dúvida específica?\n\n"
                "_Escreva sua pergunta livremente..._"
            )
            return {"texto": prompt, "tipo": "menu"}
        else:
            return {"texto": "⚠️ Opção inválida. Digite o número do menu.", "tipo": "erro"}

    texto_menu, opcoes = formatar_texto_menu("MENU_INICIAL")
    session["menu_atual"] = "MENU_INICIAL"
    session["opcoes_validas"] = opcoes
    session.pop("aguardando_pergunta", None)
    return {"texto": "Desculpe, não entendi. " + texto_menu, "tipo": "menu"}