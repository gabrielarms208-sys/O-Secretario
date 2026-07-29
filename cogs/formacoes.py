from datetime import date

import discord
from discord import app_commands
from discord.ext import commands

import config
import db
import roblox_api
from import_parser import parse_formados


# ---------- Autocomplete ----------
# Sugerem, enquanto a pessoa digita, só cursos/edições que já existem no
# banco — mesmo comportamento do /xp rank que serviu de referência.

async def curso_autocomplete(interaction: discord.Interaction, current: str):
    nomes = await db.cursos_autocomplete(current)
    return [app_commands.Choice(name=n, value=n) for n in nomes]


async def edicao_autocomplete(interaction: discord.Interaction, current: str):
    # o autocomplete de edição depende do curso já escolhido no mesmo
    # comando (lido via interaction.namespace) — por isso só sugere algo
    # depois que a pessoa preencheu o campo "curso".
    curso_termo = interaction.namespace.curso
    if not curso_termo:
        return []
    curso = await db.buscar_curso_por_termo(curso_termo)
    if not curso:
        return []
    numeros = await db.edicoes_autocomplete(curso["id"], current)
    return [app_commands.Choice(name=n, value=n) for n in numeros]


class Formacoes(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    formacao_group = app_commands.Group(name="formacao", description="Formações e cursos do Exército")
    apelido_group = app_commands.Group(
        name="apelido", description="Apelidos/siglas de curso (pra busca reconhecer variações)", parent=formacao_group
    )

    @apelido_group.command(name="adicionar", description="[Admin] Associa um apelido/sigla a um curso já existente")
    @app_commands.describe(
        curso="Nome (ou apelido/sigla já reconhecida) do curso existente",
        apelido="Novo apelido/sigla a associar (ex: 'PQDT', 'Montanha')",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def apelido_adicionar(self, interaction: discord.Interaction, curso: str, apelido: str):
        curso_row = await db.buscar_curso_por_termo(curso)
        if not curso_row:
            await interaction.response.send_message(
                f"Não achei nenhum curso pra `{curso}`. Cadastre o curso primeiro com `/formacao adicionar`.",
                ephemeral=True,
            )
            return

        try:
            await db.adicionar_apelido_curso(curso_row["id"], apelido)
        except Exception:
            await interaction.response.send_message(
                f"`{apelido}` já está em uso (nesse curso ou em outro).", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"`{apelido}` agora aponta pra **{curso_row['nome']}**. ✅"
        )

    @apelido_group.command(name="listar", description="Lista os apelidos/siglas cadastrados de um curso")
    @app_commands.autocomplete(curso=curso_autocomplete)
    async def apelido_listar(self, interaction: discord.Interaction, curso: str):
        curso_row = await db.buscar_curso_por_termo(curso)
        if not curso_row:
            await interaction.response.send_message(f"Não achei nenhum curso pra `{curso}`.", ephemeral=True)
            return

        apelidos = await db.listar_apelidos_curso(curso_row["id"])
        sigla_auto = db.sigla_curso(curso_row["nome"])
        linhas = [f"• Sigla automática: **{sigla_auto}**" if sigla_auto else "• (sem sigla automática)"]
        linhas += [f"• {a['apelido']}" for a in apelidos] or ["• (nenhum apelido manual cadastrado)"]

        embed = discord.Embed(title=f"Apelidos de {curso_row['nome']}", description="\n".join(linhas))
        await interaction.response.send_message(embed=embed)

    @formacao_group.command(name="adicionar", description="Registra uma formação concluída")
    @app_commands.describe(
        roblox_username="Nome do militar no Roblox",
        curso="Nome do curso",
        edicao="Número/identificação da edição (ex: 13, 'Transferência do QEB')",
        data="Data de formação, formato DD/MM/AAAA",
        numero_sequencial="Número sequencial do curso (ex: 47), se souber",
    )
    @app_commands.autocomplete(curso=curso_autocomplete, edicao=edicao_autocomplete)
    async def adicionar(
        self,
        interaction: discord.Interaction,
        roblox_username: str,
        curso: str,
        edicao: str,
        data: str,
        numero_sequencial: int | None = None,
    ):
        try:
            data_formacao = date(*[int(p) for p in reversed(data.split("/"))])
        except Exception:
            await interaction.response.send_message("Data inválida — use o formato DD/MM/AAAA.", ephemeral=True)
            return

        militar = await db.buscar_militar_por_username(roblox_username)
        if not militar:
            await interaction.response.send_message(
                f"`{roblox_username}` não está cadastrado ainda. Use `/ficha atualizar` primeiro pra criar o registro dele.",
                ephemeral=True,
            )
            return

        curso_id = await db.get_ou_criar_curso(curso)
        edicao_id = await db.get_ou_criar_edicao(curso_id, edicao)
        await db.adicionar_formacao(militar["id"], curso_id, edicao_id, numero_sequencial, data_formacao, "manual")

        await interaction.response.send_message(
            f"Formação registrada: `{roblox_username}` — {curso} ({edicao}). ✅"
        )

    @formacao_group.command(name="remover", description="Cassa uma formação (mantém no histórico, marcada como cassada)")
    @app_commands.describe(roblox_username="Nome do militar no Roblox", curso="Nome do curso", edicao="Edição")
    @app_commands.autocomplete(curso=curso_autocomplete, edicao=edicao_autocomplete)
    async def remover(self, interaction: discord.Interaction, roblox_username: str, curso: str, edicao: str):
        militar = await db.buscar_militar_por_username(roblox_username)
        if not militar:
            await interaction.response.send_message("Militar não encontrado.", ephemeral=True)
            return

        curso_id = await db.get_ou_criar_curso(curso)
        edicao_id = await db.get_ou_criar_edicao(curso_id, edicao)
        formacao = await db.buscar_formacao_ativa_ou_cassada(militar["id"], curso_id, edicao_id)
        if not formacao:
            await interaction.response.send_message("Não achei essa formação pra esse militar.", ephemeral=True)
            return

        await db.cassar_formacao(formacao["id"], date.today())
        await interaction.response.send_message(
            f"Formação de `{roblox_username}` em {curso} ({edicao}) marcada como **cassada**. "
            f"O número (Nº{formacao['numero_sequencial']}) fica reservado pra ele caso reforme."
        )

    @formacao_group.command(name="consultar", description="Lista todas as formações de um militar")
    async def consultar(self, interaction: discord.Interaction, roblox_username: str):
        militar = await db.buscar_militar_por_username(roblox_username)
        if not militar:
            await interaction.response.send_message("Militar não encontrado.", ephemeral=True)
            return

        formacoes = await db.formacoes_por_militar(militar["id"])
        if not formacoes:
            await interaction.response.send_message(f"`{roblox_username}` ainda não tem formações registradas.")
            return

        linhas = []
        for f in formacoes:
            status = "" if f["status"] == "ativo" else " ⚠️ *(cassada)*"
            linhas.append(f"• {f['curso_nome']} — Nº{f['numero_sequencial']} — {f['data']}{status}")

        embed = discord.Embed(title=f"Formações de {roblox_username}", description="\n".join(linhas))
        await interaction.response.send_message(embed=embed)

    @formacao_group.command(name="relatorio", description="Lista todos os formados de um curso + edição")
    @app_commands.autocomplete(curso=curso_autocomplete, edicao=edicao_autocomplete)
    async def relatorio(self, interaction: discord.Interaction, curso: str, edicao: str):
        registros = await db.formacoes_por_curso_edicao(curso, edicao)
        if not registros:
            await interaction.response.send_message("Nenhum registro encontrado pra esse curso/edição.")
            return

        linhas = []
        for r in registros:
            status = "" if r["status"] == "ativo" else " ⚠️ *(cassada)*"
            linhas.append(f"• {r['roblox_username']} — Nº{r['numero_sequencial']}{status}")

        titulo = f"{curso} — Edição {edicao}"
        embed = discord.Embed(title=titulo, description="\n".join(linhas))
        await interaction.response.send_message(embed=embed)

    @formacao_group.command(name="importar", description="[Admin] Importa formações lendo o fórum do Decex")
    @app_commands.checks.has_permissions(administrator=True)
    async def importar(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        canais = [self.bot.get_channel(cid) for cid in config.CHANNEL_IDS_FORMACOES]
        canais = [c for c in canais if c is not None]
        if not canais:
            await interaction.followup.send(
                "Não encontrei nenhum canal de formações configurado (CHANNEL_ID_FORMACOES / CHANNEL_IDS_FORMACOES_EXTRA)."
            )
            return

        total, avisos = 0, []

        async def processa_thread(thread: discord.Thread):
            nonlocal total
            nome_curso = thread.name.strip()
            async for msg in thread.history(limit=None, oldest_first=True):
                if not msg.content:
                    continue
                registros = parse_formados(msg.content, nome_curso_padrao=nome_curso)
                if not registros:
                    continue

                # resolve os usernames que ainda não existem no banco em UM
                # lote só (mais rápido e mais gentil com a API do Roblox do
                # que resolver um por um)
                a_resolver = []
                for r in registros:
                    if not await db.buscar_militar_por_username(r["username"]):
                        a_resolver.append(r["username"])
                ids_resolvidos = await roblox_api.resolver_ids(a_resolver) if a_resolver else {}

                for r in registros:
                    militar = await db.buscar_militar_por_username(r["username"])
                    if not militar:
                        roblox_id = ids_resolvidos.get(r["username"])
                        militar_id = await db.upsert_militar(roblox_id=roblox_id, roblox_username=r["username"])
                    else:
                        militar_id = militar["id"]

                    curso_id = await db.get_ou_criar_curso(r["curso"])
                    edicao_id = await db.get_ou_criar_edicao(curso_id, r["edicao"], r["edicao_apelido"])

                    if r["cassado"]:
                        formacao_id = await db.adicionar_formacao(
                            militar_id, curso_id, edicao_id, r["numero_sequencial"], date.today(), "importado-forum"
                        )
                        await db.cassar_formacao(formacao_id, date.today())
                    else:
                        await db.adicionar_formacao(
                            militar_id, curso_id, edicao_id, r["numero_sequencial"], date.today(), "importado-forum"
                        )
                    total += 1

        for canal in canais:
            for thread in canal.threads:
                await processa_thread(thread)
            async for thread in canal.archived_threads(limit=None):
                await processa_thread(thread)

        await interaction.followup.send(
            f"Importação concluída: {total} formações processadas.\n"
            f"⚠️ As datas exatas de formação não vieram no texto original, então foram gravadas com a data de hoje "
            f"— ajuste manualmente com `/formacao adicionar` se precisar da data real de cada uma."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Formacoes(bot))
