# 🤖 Bot Nubia

> Tecnologia é o meio, a solução é o fim.

O **Bot Nubia** é um assistente virtual inteligente e híbrido para **atendimento automatizado via WhatsApp**, combinando **Node.js** (comunicação em tempo real) e **Python** (Inteligência Artificial e processamento de dados).

📌 **Indicado para desenvolvedores** que desejam estudar, prototipar ou implementar bots de atendimento automatizado com IA, integração multimodal e escalabilidade.

---

## 📌 Visão Geral

- Comunicação via WhatsApp Web
- IA generativa com busca semântica
- Arquitetura em microsserviços
- Suporte a mídia (áudio, PDF, imagens)
- Escalonamento para atendimento humano

---

## 🧠 Arquitetura do Sistema

O projeto é composto por **dois microsserviços locais**, que se comunicam via HTTP (API local):

### 🦾 Corpo — Node.js + whatsapp-web.js
Responsável pela interação direta com o WhatsApp.

**Funções:**
- Conexão com o WhatsApp Web
- Escuta o envio de mensagens
- Envio de arquivos e áudios
- Gerenciamento de sessões

**Porta padrão:** `3000`

---

### 🧠 Cérebro — Python + FastAPI
Responsável pela lógica de negócio e Inteligência Artificial.

**Funções:**
- Processamento de mensagens
- Integração com OpenAI
- Busca semântica com Sentence Transformers
- Análise de sentimento
- Geração de áudio (TTS)
- Integração com Google Sheets

**Porta padrão:** `8000`

---

## 🔄 Fluxo Básico de Funcionamento

1. Usuário envia uma mensagem no WhatsApp  
2. O **Node.js** recebe a mensagem  
3. A mensagem é enviada para a API **Python**  
4. A IA processa e gera a resposta  
5. O **Node.js** envia a resposta ao usuário  

---

## 🚀 Funcionalidades

- ✅ **IA Generativa:** Respostas humanizadas usando GPT-4o  
- ✅ **Busca Vetorial:** Respostas mesmo com perguntas imprecisas  
- ✅ **Menus Interativos:** Fluxos guiados ou perguntas livres  
- ✅ **Privacidade:** Mascaramento automático de CPF, e-mail e matrícula  
- ✅ **Gestão de Mídia:** Áudios, PDFs e imagens  
- ✅ **Sincronização de Grupos:** Atualização automática  
- ✅ **Modo Transbordo:** Encaminhamento para atendimento humano  

---

## 🛠️ Pré-requisitos

Antes de começar, você precisará de:

- [Node.js](https://nodejs.org/) **v16+**
- [Python](https://www.python.org/) **v3.9+**
- Conta no **Google Cloud** (API do Google Sheets)
- **Chave de API da OpenAI**

---

## ⚙️ Instalação e Configuração

### 1️⃣ Clone o Repositório
```bash
git clone https://github.com/davicampos18/bot-nubia.git
cd bot-nubia
```

### 2️⃣ Configurando o Backend (Python – Cérebro)
```bash
# Criar ambiente virtual
python -m venv venv

# Ativar ambiente
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Instalar dependências
pip install -r requirements.txt
```

**📌 Configuração obrigatória:**
- Crie config.py e credentials.json na raiz
- Use config.example.py como base
- Insira suas chaves da OpenAI e Google

### 3️⃣ Configurando o Frontend (Node.js – Corpo)
```bash
npm install
```

### ▶️ Como Rodar o Projeto Localmente
Você deve executar os **dois serviços simultaneamente.**

#### Terminal 1 — Cérebro (Python)
```bash
# Certifique-se de que o venv está ativo
python main.py
```
Servidor disponível em:
👉 http://127.0.0.1:8000

#### Terminal 2 — Corpo (Node.js)
```bash
node bot.js
```
Servidor disponível em:
👉 http://127.0.0.1:3000

📱 Um **QR Code** será exibido para conectar ao WhatsApp.

**💡 Dica (Windows):**
Use o arquivo start_local.bat para iniciar tudo automaticamente.

## ☁️ (Opcional) Módulo Cloud Bridge — API em Nuvem

Este módulo é opcional e necessário apenas se você quiser integrar o bot com um painel de atendimento humano (Call Center) e persistência de dados na nuvem.

### 📂 Localização
/cloud

### 🛠️ Tecnologias Utilizadas

- FastAPI
- Supabase (PostgreSQL + Realtime)
- Pydantic

### 🔗 Funcionamento

1. O bot local envia mensagens para /sync/mensagem
2. Consulta /sync/fila_pendente para mensagens do atendente
3. Suporte a áudio, imagem e documentos via Base64

### ▶️ Executando o Cloud Bridge
```bash
cd cloud
pip install -r requirements.txt
uvicorn main:app --reload
```

## 🛡️ Aviso Legal

Este projeto utiliza a biblioteca **whatsapp-web.js**, que **não é oficial** do WhatsApp.
O uso de bots automatizados pode violar os termos de serviço da plataforma.

### ⚠️ Use com responsabilidade e ética.
Conhecimento não é crime, mas o uso indevido tem consequências.