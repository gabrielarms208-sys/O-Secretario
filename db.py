import aiosqlite
import os
from datetime import date

import config

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


async def iniciar_banco():
    """Cria o banco e as tabelas se ainda não existirem. Chame 1x na subida do bot."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            await db.executescript(f.read())
        await db.commit()


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
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM militares WHERE roblox_username = ? COLLATE NOCASE", (roblox_username,)
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

async def get_ou_criar_curso(nome: str) -> int:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cur = await db.execute("SELECT id FROM cursos WHERE nome = ? COLLATE NOCASE", (nome,))
        row = await cur.fetchone()
        if row:
            return row[0]
        cur = await db.execute("INSERT INTO cursos (nome) VALUES (?)", (nome,))
        await db.commit()
        return cur.lastrowid


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
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT f.*, m.roblox_username, e.apelido AS edicao_apelido "
            "FROM formacoes f "
            "JOIN militares m ON m.id = f.militar_id "
            "JOIN cursos c ON c.id = f.curso_id "
            "JOIN edicoes e ON e.id = f.edicao_id "
            "WHERE c.nome = ? COLLATE NOCASE AND e.numero = ? "
            "ORDER BY f.numero_sequencial ASC",
            (curso_nome, numero_edicao),
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
