import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

GUILD_ID_PRINCIPAL = int(os.getenv("GUILD_ID_PRINCIPAL", "0") or 0)
GUILD_ID_SGEX = int(os.getenv("GUILD_ID_SGEX", "0") or 0)
GUILD_ID_DECEX = int(os.getenv("GUILD_ID_DECEX", "0") or 0)

CHANNEL_ID_FICHAS = int(os.getenv("CHANNEL_ID_FICHAS", "0") or 0)
CHANNEL_ID_FORMACOES = int(os.getenv("CHANNEL_ID_FORMACOES", "0") or 0)

# Todos os canais de formação juntos (o principal + os extras), já prontos
# pra iterar em uma lista só na hora de importar.
CHANNEL_IDS_FORMACOES = [CHANNEL_ID_FORMACOES] if CHANNEL_ID_FORMACOES else []
CHANNEL_IDS_FORMACOES += [
    int(c.strip()) for c in os.getenv("CHANNEL_IDS_FORMACOES_EXTRA", "").split(",") if c.strip()
]

DATABASE_PATH = os.getenv("DATABASE_PATH", "ficha_militar.db")

# Lista ordenada de patentes (da mais baixa pra mais alta), usada pra
# saber se uma mudança de cargo é uma promoção e qual é a "primeira"
# patente (define a data de entrada oficial).
PATENTES = [
    p.strip() for p in os.getenv("PATENTES", "").split(",") if p.strip()
]

# Opcional: cargos do Discord que representam Organizações Militares e
# Honrarias/medalhas. Se preenchidos, o bot passa a detectar e preencher
# esses campos da ficha sozinho (igual já faz com patente), lendo os
# cargos atuais do membro no servidor Principal. Se deixar vazio, esses
# dois campos continuam só manuais (via /ficha atualizar), sem quebrar nada.
ORGANIZACOES = [c.strip() for c in os.getenv("ORGANIZACOES", "").split(",") if c.strip()]
HONRARIAS = [c.strip() for c in os.getenv("HONRARIAS", "").split(",") if c.strip()]

# Rótulos usados no campo `situacao` da ficha pros dois tipos de reserva.
# Se vocês usarem outro texto no dia a dia, só trocar aqui.
SITUACAO_RESERVA_R1 = "Reserva R/1"
SITUACAO_RESERVA_R2 = "Reserva R/2"


def validar_config():
    """Roda no início do bot pra avisar cedo se faltou configurar algo."""
    faltando = []
    if not DISCORD_TOKEN:
        faltando.append("DISCORD_TOKEN")
    if not GUILD_ID_PRINCIPAL:
        faltando.append("GUILD_ID_PRINCIPAL")
    if not GUILD_ID_SGEX:
        faltando.append("GUILD_ID_SGEX")
    if not GUILD_ID_DECEX:
        faltando.append("GUILD_ID_DECEX")
    if not CHANNEL_ID_FICHAS:
        faltando.append("CHANNEL_ID_FICHAS")
    if not CHANNEL_IDS_FORMACOES:
        faltando.append("CHANNEL_ID_FORMACOES (ou CHANNEL_IDS_FORMACOES_EXTRA)")
    if not PATENTES:
        faltando.append("PATENTES")
    if faltando:
        print("⚠️  Variáveis de ambiente faltando ou vazias: " + ", ".join(faltando))
        print("   Preencha o arquivo .env antes de usar os comandos que dependem delas.")
