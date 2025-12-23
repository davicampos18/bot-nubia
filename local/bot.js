const express = require('express');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js'); 
const axios = require('axios');
const qrcode = require('qrcode-terminal');

const app = express();
// Aumentar o limite do JSON para aceitar arquivos grandes (fotos/pdfs)
app.use(express.json({ limit: '50mb' })); 
app.use(express.urlencoded({ limit: '50mb', extended: true }));

// URL do Python Local (Cérebro)
const PYTHON_LOCAL = "http://127.0.0.1:8000";

console.log('🚀 Iniciando configuração do cliente...');

const client = new Client({
    authStrategy: new LocalAuth(), 
    puppeteer: { 
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox'] 
    }
});

// === Logs de Debug ===
client.on('loading_screen', (percent, message) => console.log('⏳ Carregando:', percent, '%', message));
client.on('qr', qr => {
    console.log('📱 QR Code gerado. Escaneie:');
    qrcode.generate(qr, { small: true });
});
client.on('authenticated', () => console.log('🔑 Autenticado!'));
client.on('auth_failure', msg => console.error('❌ Falha na autenticação:', msg));

client.on('ready', () => {
    console.log('✅ Zap Local Pronto e Conectado!');
    console.log('⏳ Aguardando 10s para sincronizar grupos...');
    setTimeout(() => {
        sincronizarGrupos();
    }, 10000); 
});

// =================================================================
// === 1. RECEBIMENTO (ATUALIZADO PARA MÍDIA) ===
// =================================================================
client.on('message', async msg => {
    if (msg.from === 'status@broadcast') return;
    if (msg.fromMe) return;
    
    let isGroup = false;
    let nome;
    let final_id;

    const chat = await msg.getChat();

    if (chat.isGroup) {
        isGroup = true;
        nome = chat.name;
        final_id = chat.id._serialized;
    } else {
        const contact = await msg.getContact();
        nome = contact.pushname || contact.name || "Usuario";
        final_id = contact.id._serialized;
    }
    
    console.log(`📩 Mensagem de ${nome}: ${msg.body.substring(0, 20)}...`);

    // --- NOVA LÓGICA DE DOWNLOAD ---
    let mediaData = {};
    if (msg.hasMedia) {
        try {
            console.log("📎 Baixando mídia recebida...");
            const media = await msg.downloadMedia();
            if (media) {
                mediaData = {
                    base64: media.data,
                    mimetype: media.mimetype,
                    filename: media.filename || 'arquivo_recebido'
                };
                console.log(`✅ Mídia baixada: ${mediaData.mimetype}`);
            }
        } catch (error) {
            console.error('❌ Erro ao baixar mídia:', error.message);
        }
    }

    try {
        await axios.post(`${PYTHON_LOCAL}/webhook/local`, {
            telefone: final_id,
            nome: nome,
            mensagem: msg.body || (msg.hasMedia ? "[Arquivo]" : ""),
            is_group: isGroup,
            original_id: final_id,
            // Passa os dados da mídia se houver
            base64: mediaData.base64 || null,
            mimetype: mediaData.mimetype || null,
            filename: mediaData.filename || null
        });
    } catch (e) {
        console.error("Erro ao falar com Python:", e.message);
    }
});

// =================================================================
// === HELPER: Formatar ID do WhatsApp ===
// =================================================================
function formatarChatId(numero) {
    if (!numero) return null;
    let chatId = numero;
    if (!chatId.includes('@')) {
        chatId = `${chatId}@c.us`;
    }
    return chatId;
}

// =================================================================
// === 2. ENDPOINTS DE ENVIO (MANTIDO E FUNCIONANDO) ===
// =================================================================

// Enviar TEXTO
app.post('/enviar', async (req, res) => {
    const { telefone, texto, is_group } = req.body;
    try {
        let chatId = formatarChatId(telefone);
        if (is_group && !chatId.includes('@g.us')) {
             chatId = `${telefone}@g.us`;
        }

        const textoFinal = `\u200B${texto}`; 
        await client.sendMessage(chatId, textoFinal);
        console.log(`📤 Texto enviado para ${chatId}`);
        res.send({ ok: true });
    } catch (e) {
        console.error("Erro no envio:", e.message);
        res.status(500).send({ error: e.message });
    }
});

// Enviar IMAGEM
app.post('/enviar_imagem', async (req, res) => {
    const { number, base64, filename, caption } = req.body;
    try {
        const chatId = formatarChatId(number);
        const cleanBase64 = base64.replace(/^data:.*;base64,/, "");
        const media = new MessageMedia('image/jpeg', cleanBase64, filename);
        
        await client.sendMessage(chatId, media, { caption: caption || '' });
        console.log(`📸 Imagem enviada para ${chatId}`);
        res.send({ ok: true });
    } catch (e) {
        console.error("Erro ao enviar imagem:", e.message);
        res.status(500).send({ error: e.message });
    }
});

// Enviar ÁUDIO
app.post('/enviar_audio', async (req, res) => {
    const { number, base64 } = req.body;
    try {
        const chatId = formatarChatId(number);
        const cleanBase64 = base64.replace(/^data:.*;base64,/, "");
        const media = new MessageMedia('audio/mp3', cleanBase64, 'audio.mp3');
        
        await client.sendMessage(chatId, media, { sendAudioAsVoice: true });
        console.log(`🎤 Áudio enviado para ${chatId}`);
        res.send({ ok: true });
    } catch (e) {
        console.error("Erro ao enviar áudio:", e.message);
        res.status(500).send({ error: e.message });
    }
});

// Enviar ARQUIVO
app.post('/enviar_arquivo', async (req, res) => {
    const { number, base64, filename, caption } = req.body;
    try {
        const chatId = formatarChatId(number);
        // Garante limpeza do base64
        const cleanBase64 = base64.replace(/^data:.*;base64,/, "");
        
        // --- MELHORIA: Detectar Mimetype pela extensão ---
        let mimetype = 'application/octet-stream'; // Padrão
        const ext = filename.split('.').pop().toLowerCase();

        const mimeMap = {
            'pdf': 'application/pdf',
            'doc': 'application/msword',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'xls': 'application/vnd.ms-excel',
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'ppt': 'application/vnd.ms-powerpoint',
            'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'txt': 'text/plain',
            'csv': 'text/csv',
            'jpg': 'image/jpeg',
            'png': 'image/png',
            'mp3': 'audio/mpeg',
            'mp4': 'video/mp4'
        };

        if (mimeMap[ext]) {
            mimetype = mimeMap[ext];
        }
        // -------------------------------------------------

        const media = new MessageMedia(mimetype, cleanBase64, filename);
        
        await client.sendMessage(chatId, media, { caption: caption || '' });
        console.log(`📎 Arquivo (${ext}) enviado para ${chatId}`);
        res.send({ ok: true });
    } catch (e) {
        console.error("Erro ao enviar arquivo:", e.message);
        res.status(500).send({ error: e.message });
    }
});

// === 3. SINCRONIZAÇÃO DE GRUPOS ===
async function sincronizarGrupos() {
    console.log('🔄 Iniciando varredura de grupos...');
    try {
        const chats = await client.getChats();
        const grupos = chats.filter(chat => chat.isGroup);

        if (grupos.length > 0) {
            const listaGrupos = grupos.map(g => ({
                id: g.id._serialized, 
                nome: g.name,
                qtd: g.participants ? g.participants.length : 0
            }));
            
            await axios.post(`${PYTHON_LOCAL}/sync/listas_local`, listaGrupos);
            console.log(`✅ ${listaGrupos.length} grupos enviados para o Python.`);
        }
    } catch (e) {
        console.error("❌ Erro ao sincronizar grupos:", e.message);
    }
}

// Inicializa
console.log('⚙️ Inicializando cliente do WhatsApp...');
client.initialize();
app.listen(3000, () => console.log('🤖 Bot API rodando na porta 3000'));