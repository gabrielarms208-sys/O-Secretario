"""
Parsers de texto livre pros fóruns do Discord.

1) parse_ficha: posts do fórum "ficha-militar" (SGEx) — texto com campos
   tipo "▷Posto: X;" um por linha. Também extrai "Feitos" (campo novo) e
   "Medalhas" (vai pro campo `honrarias`).

2) parse_formados: posts dos fóruns de formados (formados-cursos,
   formados-estágios, formados-escolas-academias). Versão TOLERANTE — o
   formato original exigia exatamente "- usuario → Curso Nº12" com
   cabeçalho "# Edição" antes. Agora aceita variações comuns:
     - separador entre usuário e curso: →, —, - (cercado de espaço), ou :
     - "Nº"/"N°"/"nº"/"#" antes do número, OU número sem prefixo nenhum,
       OU sem número nenhum (numero_sequencial fica None)
     - cabeçalho de edição com # (Markdown) OU em negrito tipo "**1ª Edição**"
     - linha só com o nome, sem separador nenhum (vira registro sem curso
       explícito — usa o nome da thread)

Esses parsers são tolerantes: se um campo não bater, ele simplesmente
não é preenchido, em vez de quebrar a importação inteira. Ficha sem
os campos principais é marcada como incompleta pra revisão manual.
"""
import re
from datetime import datetime


def _parse_data(txt: str):
    """Aceita DD/MM/AAAA. Retorna objeto date ou None se não bater."""
    txt = txt.strip().rstrip(".;")
    try:
        return datetime.strptime(txt, "%d/%m/%Y").date()
    except ValueError:
        return None


def parse_ficha(texto: str) -> dict:
    """Extrai os campos de um post de ficha militar. Retorna um dict pronto
    pra passar pro db.upsert_ficha, mais a chave 'ficha_completa'."""
    campos = {}

    def campo(label, alvo=None):
        m = re.search(rf"{label}\s*:\s*(.+)", texto, re.IGNORECASE)
        return m.group(1).strip().rstrip(".;") if m else None

    posto = campo("Posto")
    if posto:
        campos["posto"] = posto

    data_entrada = campo("Data de entrada")
    if data_entrada:
        d = _parse_data(data_entrada)
        if d:
            campos["data_entrada"] = d.isoformat()

    ultima_promocao = campo(r"[UÚ]ltima data de promo[cç][ãa]o")
    if ultima_promocao:
        d = _parse_data(ultima_promocao)
        if d:
            campos["ultima_promocao"] = d.isoformat()

    situacao = campo(r"Situa[cç][ãa]o Atual")
    if situacao:
        campos["situacao"] = situacao

    arma = campo("Arma")
    if arma:
        campos["arma"] = arma

    # Organizações Militares: bloco de linhas com "▷" entre o cabeçalho
    # "Organizações Militares" e o próximo cabeçalho em negrito.
    orgs = _extrair_bloco(texto, r"Organiza[cç][õo]es Militares", r"Dados Funcionais|Feitos|Medalhas|Forma[cç][õo]es")
    if orgs:
        campos["organizacoes"] = "; ".join(orgs)

    # "Feitos": lista livre da carreira do militar (cargos que já ocupou,
    # cursos que formulou, etc). Vira um campo novo e separado de Medalhas.
    feitos = _extrair_bloco(texto, r"Feitos", r"Medalhas|Forma[cç][õo]es|$")
    if feitos:
        campos["feitos"] = "; ".join(feitos)

    # "Medalhas": vai pro campo `honrarias` (mesmo propósito, nome já usado
    # no resto do bot desde antes de vermos esse formato específico de ficha).
    medalhas = _extrair_bloco(texto, r"Medalhas", r"Forma[cç][õo]es|$")
    if medalhas:
        campos["honrarias"] = "; ".join(medalhas)

    campos["ficha_completa"] = 1 if (posto and data_entrada) else 0

    return campos


def _extrair_bloco(texto: str, inicio_regex: str, fim_regex: str) -> list[str]:
    m_inicio = re.search(inicio_regex, texto, re.IGNORECASE)
    if not m_inicio:
        return []
    resto = texto[m_inicio.end():]
    m_fim = re.search(fim_regex, resto, re.IGNORECASE)
    bloco = resto[: m_fim.start()] if m_fim else resto
    linhas = []
    for linha in bloco.splitlines():
        linha = linha.strip().lstrip("▷").strip().rstrip(".;").strip()
        if linha:
            linhas.append(linha)
    return linhas


# ---------- Parser do fórum de formados (versão flexível) ----------

# Cabeçalho de edição: "# 1ª Edição", "## 1ª Edição (algo)", ou em negrito
# "**1ª Edição**", com ou sem emoji customizado do Discord no final.
_RE_EDICAO = re.compile(
    r"^(?:#+\s*|\*\*\s*)(.+?)(?:\s*\*\*)?\s*(?:<a?:\w+:\d+>)?\s*$"
)

# Reconhece só cabeçalhos que "parecem" edição/turma/estágio — evita que
# qualquer linha em negrito vire uma "edição" por engano.
_PALAVRAS_EDICAO = re.compile(r"edi[cç][ãa]o|turma|est[áa]gio|academia|transfer[êe]ncia", re.IGNORECASE)

# Separadores aceitos entre "usuário" e o resto da linha (curso/turma/etc)
_SEPARADORES = [" → ", " — ", " - ", ": ", "→", "—", ":"]

# Número sequencial em qualquer um desses formatos: Nº12, N°12, nº 12, #12,
# ou simplesmente um número solto no fim da linha.
_RE_NUMERO = re.compile(r"(?:N[ºo°]|#)\s*(\d+)|(\d+)\s*$")


def _e_cabecalho_edicao(linha: str) -> str | None:
    """Retorna o título da edição se a linha parecer um cabeçalho de
    edição/turma/estágio, senão None."""
    if not (linha.startswith("#") or linha.startswith("**")):
        return None
    m = _RE_EDICAO.match(linha)
    if not m:
        return None
    titulo = m.group(1).strip()
    # só considera cabeçalho de verdade se tiver uma palavra-chave conhecida
    # OU for bem curto e começar com número+ª/º (ex: "1ª Edição", "Turma 3")
    if _PALAVRAS_EDICAO.search(titulo) or re.match(r"^\d+\s*[ªº°]", titulo):
        return titulo
    return None


def _dividir_edicao_apelido(titulo: str):
    m_partes = re.match(r"(.+?)\s*(\(.+\))?$", titulo)
    numero = m_partes.group(1).strip() if m_partes else titulo
    apelido = m_partes.group(2) if m_partes and m_partes.group(2) else None
    return numero, apelido


def parse_formados(texto: str, nome_curso_padrao: str | None = None):
    """Lê um post inteiro de formados e retorna uma lista de dicts:
    {username, curso, edicao, edicao_apelido, numero_sequencial, cassado}.

    Mais tolerante que a versão anterior: aceita vários separadores e não
    exige mais que o número sequencial esteja presente."""
    resultados = []
    edicao_atual = None
    edicao_apelido_atual = None

    for linha_bruta in texto.splitlines():
        linha = linha_bruta.strip()
        if not linha:
            continue

        titulo_edicao = _e_cabecalho_edicao(linha)
        if titulo_edicao:
            edicao_atual, edicao_apelido_atual = _dividir_edicao_apelido(titulo_edicao)
            continue

        if linha.upper() in ("N/A", "NENHUM", "-"):
            continue

        # só processa linha de membro se ela parecer um item de lista
        if not (linha.startswith("-") or linha.startswith("•") or linha.startswith("*")):
            continue

        conteudo = linha.lstrip("-•*").strip()
        if not conteudo:
            continue

        cassado = bool(re.search(r"\*\*forma[cç][ãa]o removida\*\*", conteudo, re.IGNORECASE))
        conteudo_limpo = re.sub(r"\*\*forma[cç][ãa]o removida\*\*", "", conteudo, flags=re.IGNORECASE).strip()

        username = None
        curso_label = None
        for sep in _SEPARADORES:
            if sep in conteudo_limpo:
                esquerda, direita = conteudo_limpo.split(sep, 1)
                username = esquerda.strip()
                curso_label = direita.strip()
                break

        if username is None:
            # não achou separador — a linha inteira é o username
            username = conteudo_limpo.strip()
            curso_label = None

        if not username:
            continue

        numero_sequencial = None
        if curso_label:
            m_num = _RE_NUMERO.search(curso_label)
            if m_num:
                numero_sequencial = int(m_num.group(1) or m_num.group(2))
                curso_label = _RE_NUMERO.sub("", curso_label).strip().rstrip(".,;")

        resultados.append(
            {
                "username": username,
                "curso": (nome_curso_padrao or curso_label or "Não especificado").strip(),
                "edicao": edicao_atual or "Única",
                "edicao_apelido": edicao_apelido_atual,
                "numero_sequencial": numero_sequencial,
                "cassado": cassado,
            }
        )

    return resultados
