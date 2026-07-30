import aiosqlite
import os
import re
import unicodedata
from datetime import date

import config

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

# Palavras que não entram na sigla automática de um curso (ex: "Curso de
# Operações na Selva" -> ignora "de"/"na" -> sigla "COS", não "CDONS").
_STOPWORDS_SIGLA = {"de", "da", "do", "das", "dos", "e", "em", "na", "no", "nas", "nos", "para", "com", "a", "o"}


def _normalizar(txt: str) -> str:
    """minúsculo + sem acento + sem espaço extra, pra comparar 'Paraquedista'
    com 'paraquedista', 'Montanha' com 'montanha', etc."""
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", txt).strip().lower()


def _sigla(nome: str) -> str:
    """Gera a sigla de um nome de curso a partir das iniciais das palavras
    significativas. 'Curso de Operações na Selva' -> 'COS'."""
    palavras = re.findall(r"[A-Za-zÀ-ÿ]+", nome)
    letras = [p[0] for p in palavras if p.lower() not in _STOPWORDS_SIGLA]
    return "".join(letras).upper()


# Palavras "neutras" demais pra identificar um curso sozinhas (aparecem em
# quase todo nome/estágio e não devem, por si só, fazer dois cursos
# diferentes baterem na busca). São ignoradas ao comparar tokens.
_PALAVRAS_GENERICAS = {
    "curso", "estagio", "estágio", "basico", "básico", "avancado", "avançado",
    "adaptacao", "adaptação", "aclimatacao", "aclimatação", "treinamento",
    "formacao", "formação", "nivel", "nível", "modulo", "módulo", "geral",
}

# Grupos de sinônimos pra reconhecimento automático ("por osmose"), sem
# precisar cadastrar apelido manual pra cada variação comum. Cada grupo é
# um conjunto de palavras/abreviações que se referem à mesma coisa — se o
# termo digitado E o nome do curso tiverem pelo menos uma palavra em comum
# (direto ou via grupo), o bot considera que bateu. De propósito NÃO
# incluímos palavras genéricas aqui (tipo "estágio"/"básico") — só o que
# realmente identifica do que se trata o curso.
# Ajuste/expanda essa lista conforme o catálogo de cursos de vocês crescer.
_GRUPOS_SINONIMOS = [
    {"pqdt", "paraquedista", "paraquedismo", "aerotransportado", "breve", "brevê"},
    {"selva", "selvas", "cos", "floresta"},
    {"montanha", "montanhismo", "alpinismo", "alpino"},
    {"comando", "comandos", "cac", "acoes de comando", "operacoes especiais", "forcas especiais"},
    {"blindado", "blindados", "blindada", "cavalaria"},
    {"dompsa"},
    {"precursor", "precursores"},
    {"oficial", "oficiais", "aman"},
    {"sargento", "sargentos", "esa"},
    {"artilharia", "art"},
    {"engenharia", "eng"},
    {"inteligencia", "inteligência", "intel"},
]


def _expandir_sinonimos(tokens: set[str]) -> set[str]:
    """Recebe um conjunto de palavras já normalizadas e devolve o mesmo
    conjunto acrescido de todos os sinônimos dos grupos que baterem."""
    expandido = set(tokens)
    for grupo in _GRUPOS_SINONIMOS:
        if tokens & grupo:
            expandido |= grupo
    return expandido


def _tokens(txt_normalizado: str) -> set[str]:
    """Quebra em palavras, removendo preposições e palavras genéricas
    demais pra não causar falso-positivo entre cursos diferentes."""
    return {
        t for t in txt_normalizado.split(" ")
        if t and t not in _STOPWORDS_SIGLA and t not in _PALAVRAS_GENERICAS
    }


async def iniciar_banco():
    """Cria o banco e as tabelas se ainda não existirem. Chame 1x na subida do bot."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            await db.executescript(f.read())
        await db.commit()
        await _migrar_schema(db)
        await db.commit()


async def _migrar_schema(db: aiosqlite.Connection):
    """Ajustes que `CREATE TABLE IF NOT EXISTS` não cobre (ele não adiciona
    coluna nova numa tabela que já existe). Cada migração checa antes de
    aplicar, então é seguro rodar isso toda vez que o bot sobe."""
    cur = await db.execute("PRAGMA table_info(fichas)")
    colunas = {row[1] for row in await cur.fetchall()}
    if "feitos" not in colunas:
        await db.execute("ALTER TABLE fichas ADD COLUMN feitos TEXT")
    if "thread_id" not in colunas:
        # guarda a thread do fórum de fichas onde o `/ficha criar` postou/
        # atualizou essa ficha, pra saber se já existe uma e só editar em
        # vez de criar uma thread duplicada da próxima vez
        await db.execute("ALTER TABLE fichas ADD COLUMN thread_id BIGINT")
    if "thread_message_id" not in colunas:
        await db.execute("ALTER TABLE fichas ADD COLUMN thread_message_id BIGINT")



# ---------- Militares ----------

async def upsert_militar(roblox_id: int | None, roblox_username: str, discord_id: int | None = None) -> int:
    """Cria o militar se não existir e sempre atualiza o username (caso tenha
    trocado). Busca primeiro por roblox_id (chave estável); se não tiver um
    roblox_id ainda resolvido, cai pra busca por username pra não duplicar
    o registro quando o ID for resolvido depois. Retorna o id interno."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        row = None
        if roblox_id:
            cur = await db.execute("SELECT id FROM militares WHERE roblox_id = ?", (roblox_id,))
            row = await cur.fetchone()
        if not row:
            cur = await db.execute(
                "SELECT id FROM militares WHERE roblox_username = ? COLLATE NOCASE", (roblox_username,)
            )
            row = await cur.fetchone()

        if row:
            militar_id = row[0]
            await db.execute(
                "UPDATE militares SET roblox_username = ?, "
                "roblox_id = COALESCE(?, roblox_id), "
                "discord_id = COALESCE(?, discord_id), "
                "atualizado_em = CURRENT_TIMESTAMP WHERE id = ?",
                (roblox_username, roblox_id, discord_id, militar_id),
            )
        else:
            cur = await db.execute(
                "INSERT INTO militares (roblox_id, roblox_username, discord_id) VALUES (?, ?, ?)",
                (roblox_id, roblox_username, discord_id),
            )
            militar_id = cur.lastrowid
        await db.commit()
        return militar_id


async def buscar_militar_por_username(roblox_username: str):
    """Busca ignorando maiúsculas/minúsculas E espaços extras no início/fim
    (comuns em copiar-e-colar), pra evitar falso 'militar não encontrado'."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM militares WHERE TRIM(roblox_username) = TRIM(?) COLLATE NOCASE",
            (roblox_username,),
        )
        return await cur.fetchone()


# ---------- Fichas ----------

async def upsert_ficha(militar_id: int, campos: dict, fonte_import: str = "manual"):
    """Atualiza só os campos passados em `campos`; cria a linha se não existir.
    `campos` pode ter: posto, data_entrada, ultima_promocao, situacao, arma,
    organizacoes, honrarias, ficha_completa."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cur = await db.execute("SELECT militar_id FROM fichas WHERE militar_id = ?", (militar_id,))
        existe = await cur.fetchone()

        if not existe:
            await db.execute(
                "INSERT INTO fichas (militar_id, fonte_import) VALUES (?, ?)",
                (militar_id, fonte_import),
            )

        if campos:
            sets = ", ".join(f"{k} = ?" for k in campos.keys())
            valores = list(campos.values()) + [militar_id]
            await db.execute(
                f"UPDATE fichas SET {sets}, atualizado_em = CURRENT_TIMESTAMP WHERE militar_id = ?",
                valores,
            )
        await db.commit()


async def buscar_ficha(militar_id: int):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM fichas WHERE militar_id = ?", (militar_id,))
        return await cur.fetchone()


async def salvar_thread_ficha(militar_id: int, thread_id: int, message_id: int):
    """Guarda em qual thread do fórum de fichas o `/ficha criar` postou/
    atualizou essa ficha — assim, da próxima vez, o bot edita o post
    existente em vez de criar uma thread duplicada."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE fichas SET thread_id = ?, thread_message_id = ? WHERE militar_id = ?",
            (thread_id, message_id, militar_id),
        )
        await db.commit()


# ---------- Histórico de promoções ----------

async def registrar_promocao(militar_id: int, patente: str, data_promocao: date, origem: str = "auto-cargo"):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO historico_promocoes (militar_id, patente, data, origem) VALUES (?, ?, ?, ?)",
            (militar_id, patente, data_promocao.isoformat(), origem),
        )
        await db.commit()


async def primeira_promocao(militar_id: int):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM historico_promocoes WHERE militar_id = ? ORDER BY data ASC LIMIT 1",
            (militar_id,),
        )
        return await cur.fetchone()


# ---------- Cursos / edições ----------

async def buscar_curso_por_termo(termo: str):
    """Tenta achar um curso já cadastrado a partir de um texto livre,
    checando nessa ordem: nome exato, apelido cadastrado, sigla automática
    (iniciais do nome) e por fim um "contém" nos dois sentidos (ex: termo
    'Montanha' bate em curso 'Curso Básico de Montanha', e vice-versa).
    Retorna a linha do curso (Row) ou None se não achar nada."""
    termo_norm = _normalizar(termo)
    termo_sigla = re.sub(r"[^A-Za-zÀ-ÿ]", "", termo).upper()

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 1) nome exato
        cur = await db.execute("SELECT * FROM cursos WHERE nome = ? COLLATE NOCASE", (termo,))
        row = await cur.fetchone()
        if row:
            return row

        # 2) apelido cadastrado manualmente
        cur = await db.execute(
            "SELECT c.* FROM cursos c JOIN curso_apelidos a ON a.curso_id = c.id "
            "WHERE a.apelido = ? COLLATE NOCASE",
            (termo,),
        )
        row = await cur.fetchone()
        if row:
            return row

        # 3) sigla automática (iniciais) e "contém" — precisa varrer os
        # cursos existentes pra comparar nome normalizado / sigla
        cur = await db.execute("SELECT * FROM cursos")
        todos = await cur.fetchall()

        for c in todos:
            nome_norm = _normalizar(c["nome"])
            if _sigla(c["nome"]) == termo_sigla and termo_sigla:
                return c
            if termo_norm in nome_norm or nome_norm in termo_norm:
                return c

        # 4) sinônimos ("por osmose") — ex: termo "PQDT" bate em curso
        # "Curso Básico Paraquedista" porque os dois têm uma palavra do
        # mesmo grupo de sinônimo ("pqdt" e "paraquedista")
        tokens_termo = _expandir_sinonimos(_tokens(termo_norm))
        for c in todos:
            tokens_nome = _tokens(_normalizar(c["nome"]))
            if tokens_termo & tokens_nome:
                return c

        return None


async def buscar_curso_por_nome_exato(nome: str):
    """Busca só por nome exato (ignorando maiúscula/minúscula), SEM a
    lógica difusa de apelido/sigla/contém/sinônimos. Usada na importação
    automática (`/formacao importar`), onde o nome já vem certo e completo
    (título da thread do fórum) — usar a busca difusa aqui causava cursos
    diferentes (ex: 'Curso de Operações na Selva' e 'Estágio de Adaptação
    e Vida na Selva') sendo fundidos incorretamente no mesmo registro só
    por compartilharem uma palavra/sinônimo."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM cursos WHERE nome = ? COLLATE NOCASE", (nome,))
        return await cur.fetchone()


async def get_ou_criar_curso(nome: str, estrito: bool = False) -> int:
    """Acha o curso e cria se não existir.

    estrito=False (padrão): usa a busca "inteligente" (apelido/sigla/contém/
    sinônimos) — pra quando uma PESSOA digita o nome manualmente num
    comando, onde reconhecer variações ("PQDT" = "Paraquedista") é útil.

    estrito=True: usa só nome exato — pra importação automática de threads
    do fórum, onde cada thread já É o nome oficial e completo do curso, e
    a busca difusa causaria fusões indevidas entre cursos diferentes."""
    existente = await buscar_curso_por_nome_exato(nome) if estrito else await buscar_curso_por_termo(nome)
    if existente:
        return existente["id"]

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cur = await db.execute("INSERT INTO cursos (nome) VALUES (?)", (nome,))
        await db.commit()
        return cur.lastrowid


async def resetar_catalogo_formacoes():
    """[Destrutivo] Apaga TODAS as formações, edições e cursos cadastrados
    — usado pra limpar dados incorretos (ex: cursos fundidos por engano)
    antes de rodar `/formacao importar` de novo do zero. NÃO mexe nas
    fichas nem no cadastro de militares."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute("DELETE FROM formacoes")
        await db.execute("DELETE FROM edicoes")
        await db.execute("DELETE FROM cursos")
        await db.execute("DELETE FROM curso_apelidos")
        await db.commit()


async def adicionar_apelido_curso(curso_id: int, apelido: str):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO curso_apelidos (curso_id, apelido) VALUES (?, ?)", (curso_id, apelido)
        )
        await db.commit()


async def listar_apelidos_curso(curso_id: int):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM curso_apelidos WHERE curso_id = ?", (curso_id,))
        return await cur.fetchall()


def sigla_curso(nome: str) -> str:
    """Versão pública de `_sigla`, pra uso fora deste módulo (ex: mostrar
    a sigla automática de um curso num comando do bot)."""
    return _sigla(nome)


async def listar_cursos():
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM cursos ORDER BY nome")
        return await cur.fetchall()


async def get_ou_criar_edicao(curso_id: int, numero: str, apelido: str | None = None) -> int:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM edicoes WHERE curso_id = ? AND numero = ?", (curso_id, numero)
        )
        row = await cur.fetchone()
        if row:
            return row[0]
        cur = await db.execute(
            "INSERT INTO edicoes (curso_id, numero, apelido) VALUES (?, ?, ?)",
            (curso_id, numero, apelido),
        )
        await db.commit()
        return cur.lastrowid


# ---------- Formações ----------

async def buscar_formacao_ativa_ou_cassada(militar_id: int, curso_id: int, edicao_id: int):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM formacoes WHERE militar_id = ? AND curso_id = ? AND edicao_id = ?",
            (militar_id, curso_id, edicao_id),
        )
        return await cur.fetchone()


async def adicionar_formacao(militar_id: int, curso_id: int, edicao_id: int, numero_sequencial: int | None,
                              data_formacao: date, fonte_import: str = "manual"):
    """Se já existir um registro cassado pra esse militar/curso/edição, reativa
    e reaproveita o número. Senão cria um novo."""
    existente = await buscar_formacao_ativa_ou_cassada(militar_id, curso_id, edicao_id)
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        if existente:
            await db.execute(
                "UPDATE formacoes SET status = 'ativo', data = ?, data_cassacao = NULL WHERE id = ?",
                (data_formacao.isoformat(), existente["id"]),
            )
            formacao_id = existente["id"]
        else:
            cur = await db.execute(
                "INSERT INTO formacoes (militar_id, curso_id, edicao_id, numero_sequencial, data, fonte_import) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (militar_id, curso_id, edicao_id, numero_sequencial, data_formacao.isoformat(), fonte_import),
            )
            formacao_id = cur.lastrowid
        await db.commit()
        return formacao_id


async def cassar_formacao(formacao_id: int, data_cassacao: date):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE formacoes SET status = 'cassado', data_cassacao = ? WHERE id = ?",
            (data_cassacao.isoformat(), formacao_id),
        )
        await db.commit()


async def formacoes_por_militar(militar_id: int):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT f.*, c.nome AS curso_nome, e.numero AS edicao_numero, e.apelido AS edicao_apelido "
            "FROM formacoes f "
            "JOIN cursos c ON c.id = f.curso_id "
            "JOIN edicoes e ON e.id = f.edicao_id "
            "WHERE f.militar_id = ? ORDER BY f.data ASC",
            (militar_id,),
        )
        return await cur.fetchall()


async def formacoes_por_curso_edicao(curso_nome: str, numero_edicao: str):
    curso = await buscar_curso_por_termo(curso_nome)
    if not curso:
        return []

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT f.*, m.roblox_username, e.apelido AS edicao_apelido "
            "FROM formacoes f "
            "JOIN militares m ON m.id = f.militar_id "
            "JOIN edicoes e ON e.id = f.edicao_id "
            "WHERE f.curso_id = ? AND e.numero = ? "
            "ORDER BY f.numero_sequencial ASC",
            (curso["id"], numero_edicao),
        )
        return await cur.fetchall()


# ---------- Reserva R/1 e R/2 / arquivamento de carreira ----------

async def arquivar_e_resetar_ficha(militar_id: int, motivo: str = "reinicio-carreira-pos-r2"):
    """Guarda um snapshot (JSON) da ficha, formações e histórico de
    promoções atuais do militar numa tabela de arquivo, e depois limpa
    essas tabelas pra ele começar uma carreira nova do zero. A linha em
    `militares` (e portanto o vínculo com o roblox_id) é mantida — só o
    histórico militar "ativo" é resetado."""
    import json

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        cur = await db.execute("SELECT * FROM fichas WHERE militar_id = ?", (militar_id,))
        ficha = await cur.fetchone()

        cur = await db.execute("SELECT * FROM formacoes WHERE militar_id = ?", (militar_id,))
        formacoes = await cur.fetchall()

        cur = await db.execute("SELECT * FROM historico_promocoes WHERE militar_id = ?", (militar_id,))
        promocoes = await cur.fetchall()

        await db.execute(
            "INSERT INTO historico_fichas_arquivadas (militar_id, motivo, dados_ficha, dados_formacoes, dados_promocoes) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                militar_id,
                motivo,
                json.dumps(dict(ficha)) if ficha else None,
                json.dumps([dict(f) for f in formacoes]),
                json.dumps([dict(p) for p in promocoes]),
            ),
        )

        await db.execute("DELETE FROM fichas WHERE militar_id = ?", (militar_id,))
        await db.execute("DELETE FROM formacoes WHERE militar_id = ?", (militar_id,))
        await db.execute("DELETE FROM historico_promocoes WHERE militar_id = ?", (militar_id,))

        await db.commit()


async def historico_arquivado_por_militar(militar_id: int):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM historico_fichas_arquivadas WHERE militar_id = ? ORDER BY arquivado_em DESC",
            (militar_id,),
        )
        return await cur.fetchall()


# ---------- Documentos ----------

async def adicionar_documento(unidade: str, tipo: str, numero: str, titulo: str, link: str) -> int:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cur = await db.execute(
            "INSERT INTO documentos (unidade, tipo, numero, titulo, link) VALUES (?, ?, ?, ?, ?)",
            (unidade, tipo, numero, titulo, link),
        )
        await db.commit()
        return cur.lastrowid


async def buscar_documentos(termo: str, limite: int = 10):
    """Busca livre: bate o termo contra unidade, tipo, número e título."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        curinga = f"%{termo}%"
        cur = await db.execute(
            "SELECT * FROM documentos WHERE "
            "unidade LIKE ? OR tipo LIKE ? OR numero LIKE ? OR titulo LIKE ? "
            "ORDER BY criado_em DESC LIMIT ?",
            (curinga, curinga, curinga, curinga, limite),
        )
        return await cur.fetchall()


async def remover_documento(documento_id: int) -> bool:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cur = await db.execute("DELETE FROM documentos WHERE id = ?", (documento_id,))
        await db.commit()
        return cur.rowcount > 0


# ---------- Autocomplete ----------
# Usadas pelos comandos do bot pra sugerir, enquanto a pessoa digita, só
# valores que já existem no banco — evita erros de digitação (que causavam
# "militar não encontrado") e imita o comportamento de sugestão do /xp.

async def militares_autocomplete(termo: str, limite: int = 20):
    """Lista de usernames que batem com o texto digitado até agora."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cur = await db.execute(
            "SELECT roblox_username FROM militares WHERE roblox_username LIKE ? "
            "ORDER BY roblox_username LIMIT ?",
            (f"%{termo}%", limite),
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def cursos_autocomplete(termo: str, limite: int = 20):
    """Lista de nomes de curso que batem com o texto digitado até agora."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cur = await db.execute(
            "SELECT nome FROM cursos WHERE nome LIKE ? ORDER BY nome LIMIT ?",
            (f"%{termo}%", limite),
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def edicoes_autocomplete(curso_id: int, termo: str, limite: int = 20):
    """Lista de edições (números) de um curso específico que batem com o
    texto digitado até agora."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cur = await db.execute(
            "SELECT numero FROM edicoes WHERE curso_id = ? AND numero LIKE ? "
            "ORDER BY numero LIMIT ?",
            (curso_id, f"%{termo}%", limite),
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]
