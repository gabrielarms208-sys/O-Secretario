import discord
from discord import app_commands
from discord.ext import commands

import config
import db
import roblox_api
from import_parser import parse_ficha


class Ficha(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    ficha_group = app_commands.Group(name="ficha", description="Ficha militar dos membros")

    @ficha_group.command(name="ver", description="Mostra a ficha militar de um membro")
    @app_commands.describe(roblox_username="Nome do militar no Roblox")
    async def ver(self, interaction: discord.Interaction, roblox_username: str):
        militar = await db.buscar_militar_por_username(roblox_username)
        if not militar:
            await interaction.response.send_message(
                f"Não encontrei nenhuma ficha pra `{roblox_username}`.", ephemeral=True
            )
            return

        ficha = await db.buscar_ficha(militar["id"])
        if not ficha:
            await interaction.response.send_message(
                f"`{roblox_username}` está cadastrado, mas ainda não tem ficha preenchida.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(title=militar["roblox_username"], color=discord.Color.dark_red())
        embed.add_field(name="Posto", value=ficha["posto"] or "—", inline=True)
        embed.add_field(name="Situação", value=ficha["situacao"] or "—", inline=True)
        embed.add_field(name="Arma", value=ficha["arma"] or "—", inline=True)
        embed.add_field(name="Data de entrada", value=ficha["data_entrada"] or "—", inline=True)
        embed.add_field(name="Última promoção", value=ficha["ultima_promocao"] or "—", inline=True)
        embed.add_field(name="Organizações Militares", value=ficha["organizacoes"] or "—", inline=False)
        embed.add_field(name="Honrarias", value=ficha["honrarias"] or "—", inline=False)

        formacoes = await db.formacoes_por_militar(militar["id"])
        ativas = [f for f in formacoes if f["status"] == "ativo"]
        if ativas:
            texto = "\n".join(f"• {f['curso_nome']} (Nº{f['numero_sequencial']})" for f in ativas)
            embed.add_field(name="Formações", value=texto, inline=False)

        if not ficha["ficha_completa"]:
            embed.set_footer(text="⚠️ Ficha importada incompleta — falta revisar alguns campos.")

        await interaction.response.send_message(embed=embed)

    @ficha_group.command(name="atualizar", description="Cria ou atualiza campos da ficha de um membro (upsert)")
    @app_commands.describe(
        roblox_username="Nome do militar no Roblox",
        roblox_id="ID numérico do Roblox (só precisa na primeira vez)",
        posto="Patente/posto atual",
        situacao="Situação atual (Ativa, Licenciado, Reformado...)",
        arma="Arma (Infantaria, Blindado...)",
        organizacoes="Organizações Militares, separadas por ;",
        honrarias="Honrarias/medalhas, separadas por ;",
    )
    async def atualizar(
        self,
        interaction: discord.Interaction,
        roblox_username: str,
        roblox_id: int | None = None,
        posto: str | None = None,
        situacao: str | None = None,
        arma: str | None = None,
        organizacoes: str | None = None,
        honrarias: str | None = None,
    ):
        militar = await db.buscar_militar_por_username(roblox_username)
        if not militar:
            if not roblox_id:
                await interaction.response.send_message(
                    "Esse militar ainda não existe no banco — informe `roblox_id` na primeira vez.",
                    ephemeral=True,
                )
                return
            militar_id = await db.upsert_militar(roblox_id, roblox_username)
        else:
            militar_id = militar["id"]

        campos = {}
        if posto:
            campos["posto"] = posto
        if situacao:
            campos["situacao"] = situacao
        if arma:
            campos["arma"] = arma
        if organizacoes:
            campos["organizacoes"] = organizacoes
        if honrarias:
            campos["honrarias"] = honrarias

        await db.upsert_ficha(militar_id, campos, fonte_import="manual")
        await interaction.response.send_message(f"Ficha de `{roblox_username}` atualizada. ✅")

    @ficha_group.command(name="reserva", description="Marca um militar como Reserva R/1 ou R/2")
    @app_commands.describe(roblox_username="Nome do militar no Roblox", tipo="R/1 (pode voltar) ou R/2 (carreira encerrada)")
    @app_commands.choices(tipo=[
        app_commands.Choice(name="R/1 — pode retornar", value="R1"),
        app_commands.Choice(name="R/2 — carreira encerrada", value="R2"),
    ])
    async def reserva(self, interaction: discord.Interaction, roblox_username: str, tipo: app_commands.Choice[str]):
        militar = await db.buscar_militar_por_username(roblox_username)
        if not militar:
            await interaction.response.send_message("Militar não encontrado.", ephemeral=True)
            return

        situacao = config.SITUACAO_RESERVA_R1 if tipo.value == "R1" else config.SITUACAO_RESERVA_R2
        await db.upsert_ficha(militar["id"], {"situacao": situacao})
        await interaction.response.send_message(f"`{roblox_username}` marcado como **{situacao}**. ✅")

    @ficha_group.command(name="historico", description="Mostra carreiras antigas arquivadas de um militar (pós-R/2)")
    async def historico(self, interaction: discord.Interaction, roblox_username: str):
        militar = await db.buscar_militar_por_username(roblox_username)
        if not militar:
            await interaction.response.send_message("Militar não encontrado.", ephemeral=True)
            return

        registros = await db.historico_arquivado_por_militar(militar["id"])
        if not registros:
            await interaction.response.send_message(f"`{roblox_username}` não tem carreiras antigas arquivadas.")
            return

        import json
        linhas = []
        for r in registros:
            dados = json.loads(r["dados_ficha"]) if r["dados_ficha"] else {}
            posto = dados.get("posto", "—")
            linhas.append(f"• Arquivado em {r['arquivado_em'][:10]} — último posto: **{posto}**")

        embed = discord.Embed(
            title=f"Carreiras antigas de {roblox_username}",
            description="\n".join(linhas),
        )
        await interaction.response.send_message(embed=embed)

    @ficha_group.command(name="importar", description="[Admin] Importa/atualiza fichas lendo o fórum do SGEx")
    @app_commands.checks.has_permissions(administrator=True)
    async def importar(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        canal = self.bot.get_channel(config.CHANNEL_ID_FICHAS)
        if canal is None:
            await interaction.followup.send("Não encontrei o canal de fichas configurado (CHANNEL_ID_FICHAS).")
            return

        importadas, incompletas = 0, 0
        async for thread in canal.archived_threads(limit=None):
            importadas, incompletas = await self._importar_thread(thread, importadas, incompletas)
        for thread in canal.threads:
            importadas, incompletas = await self._importar_thread(thread, importadas, incompletas)

        await interaction.followup.send(
            f"Importação concluída: {importadas} fichas processadas, {incompletas} marcadas como incompletas "
            f"(faltando campos — precisam de revisão manual)."
        )

    async def _importar_thread(self, thread: discord.Thread, importadas: int, incompletas: int):
        primeira_msg = None
        async for msg in thread.history(limit=1, oldest_first=True):
            primeira_msg = msg
        if primeira_msg is None or not primeira_msg.content:
            return importadas, incompletas

        # o nome do militar normalmente é o título da thread ou a primeira
        # linha em negrito/link do corpo — aqui usamos o título da thread.
        roblox_username = thread.name.split(" - ")[0].strip()
        campos = parse_ficha(primeira_msg.content)

        roblox_id = await roblox_api.resolver_id(roblox_username)
        if roblox_id is None:
            # username não existe mais no Roblox (deletado/trocado) — importa
            # mesmo assim com id=0, mas fica marcado como incompleto pra revisão
            roblox_id = None
            campos["ficha_completa"] = 0

        militar_id = await db.upsert_militar(roblox_id=roblox_id, roblox_username=roblox_username)
        await db.upsert_ficha(militar_id, campos, fonte_import="importado-forum")

        importadas += 1
        if not campos.get("ficha_completa"):
            incompletas += 1
        return importadas, incompletas


async def setup(bot: commands.Bot):
    await bot.add_cog(Ficha(bot))
