"""
Parsers de texto livre pros dois formatos que vimos nos prints:

1) Posts do fórum "ficha-militar" (SGEx) — texto com campos tipo
   "▷Posto: X;" um por linha.
2) Posts do fórum "formados-cursos" (Decex) — texto com seções por
   edição ("# 1ª Edição") e linhas "- username → Curso Nº12".

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

    formacoes = _extrair_bloco(texto, r"Forma[cç][õo]es", r"$")
    if formacoes:
        # guarda só como texto solto na ficha; o registro "de verdade" e
        # pesquisável de formações vive na tabela `formacoes`, importada
        # separadamente pelo parser de formados-cursos.
        pass

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


# ---------- Parser do fórum de formados ----------

_RE_EDICAO = re.compile(r"^#+\s*(.+?)\s*(?:<a?:\w+:\d+>)?\s*$")
_RE_MEMBRO = re.compile(
    r"^-\s*([^\s→]+)\s*→\s*(.+?)\s*N[ºo°]\s*(\d+)\s*(\*\*forma[cç][ãa]o removida\*\*)?\s*$",
    re.IGNORECASE,
)


def parse_formados(texto: str, nome_curso_padrao: str | None = None):
    """Lê um post inteiro do tipo 'Atualização dos arquivos de formados' e
    retorna uma lista de dicts: {edicao, edicao_apelido, username, curso,
    numero_sequencial, cassado}."""
    resultados = []
    edicao_atual = None
    edicao_apelido_atual = None

    for linha_bruta in texto.splitlines():
        linha = linha_bruta.strip()
        if not linha:
            continue

        m_ed = _RE_EDICAO.match(linha) if linha.startswith("#") else None
        if m_ed:
            titulo = m_ed.group(1).strip()
            # separa "13ª Edição (C DoMPSA)" em numero="13" e apelido="(C DoMPSA)"
            m_partes = re.match(r"(.+?)\s*(\(.+\))?$", titulo)
            edicao_atual = m_partes.group(1).strip() if m_partes else titulo
            edicao_apelido_atual = m_partes.group(2) if m_partes and m_partes.group(2) else None
            continue

        if linha.upper() == "N/A":
            continue

        m_mem = _RE_MEMBRO.match(linha)
        if m_mem and edicao_atual:
            username, curso_label, numero, removida = m_mem.groups()
            resultados.append(
                {
                    "username": username.strip(),
                    "curso": (nome_curso_padrao or curso_label).strip(),
                    "edicao": edicao_atual,
                    "edicao_apelido": edicao_apelido_atual,
                    "numero_sequencial": int(numero),
                    "cassado": bool(removida),
                }
            )

    return resultados
