import discord
from discord import app_commands
from discord.ext import commands

import db


async def unidade_autocomplete(interaction: discord.Interaction, current: str):
    unidades = await db.unidades_autocomplete(current)
    return [app_commands.Choice(name=u, value=u) for u in unidades]


class Documentos(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    documento_group = app_commands.Group(name="documento", description="Documentos das unidades (regulamentos, decretos, ordens de serviço)")

    @documento_group.command(name="adicionar", description="[Admin] Cadastra um documento")
    @app_commands.describe(
        unidade="Unidade/órgão responsável (ex: 'Brigada de Infantaria Paraquedista', 'COEX')",
        tipo="Tipo do documento (ex: Regulamento Interno, Decreto, Ordem de Serviço)",
        numero="Número do documento",
        titulo="Título/descrição do documento",
        link="Link do documento",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def adicionar(
        self,
        interaction: discord.Interaction,
        unidade: str,
        tipo: str,
        numero: str,
        titulo: str,
        link: str,
    ):
        doc_id = await db.adicionar_documento(unidade, tipo, numero, titulo, link)
        await interaction.response.send_message(
            f"Documento cadastrado (Nº registro {doc_id}): **{tipo} {numero}** — {titulo} ✅"
        )

    @documento_group.command(name="buscar", description="Busca um documento por unidade, tipo, número ou título")
    @app_commands.describe(termo="O que buscar — ex: 'Regulamento Paraquedista', 'Decreto 15', 'COEX'")
    async def buscar(self, interaction: discord.Interaction, termo: str):
        resultados = await db.buscar_documentos(termo)
        if not resultados:
            await interaction.response.send_message(f"Nenhum documento encontrado pra `{termo}`.")
            return

        embed = discord.Embed(title=f"Resultados pra “{termo}”")
        for r in resultados:
            valor = f"[Abrir documento]({r['link']})"
            if r["unidade"]:
                valor = f"{r['unidade']} — " + valor
            embed.add_field(name=f"{r['tipo'] or 'Documento'} {r['numero'] or ''} — {r['titulo'] or ''}".strip(),
                             value=valor, inline=False)

        await interaction.response.send_message(embed=embed)

    @documento_group.command(name="por_unidade", description="Lista só os documentos de uma unidade específica")
    @app_commands.describe(
        unidade="Nome da unidade — ex: 'Regimento de Cavalaria Mecanizado'",
        termo="Opcional: filtra também por tipo, número ou título dentro dessa unidade",
    )
    @app_commands.autocomplete(unidade=unidade_autocomplete)
    async def por_unidade(self, interaction: discord.Interaction, unidade: str, termo: str | None = None):
        resultados = await db.documentos_por_unidade(unidade, termo)
        if not resultados:
            extra = f" com o termo `{termo}`" if termo else ""
            await interaction.response.send_message(
                f"Nenhum documento encontrado pra a unidade `{unidade}`{extra}."
            )
            return

        embed = discord.Embed(title=f"Documentos — {unidade}")
        for r in resultados:
            embed.add_field(
                name=f"{r['tipo'] or 'Documento'} {r['numero'] or ''} — {r['titulo'] or ''}".strip(),
                value=f"[Abrir documento]({r['link']})",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    @documento_group.command(name="remover", description="[Admin] Remove um documento pelo número de registro (Nº do /documento buscar)")
    @app_commands.checks.has_permissions(administrator=True)
    async def remover(self, interaction: discord.Interaction, registro_id: int):
        removido = await db.remover_documento(registro_id)
        if removido:
            await interaction.response.send_message(f"Documento Nº{registro_id} removido. ✅")
        else:
            await interaction.response.send_message(f"Não achei nenhum documento com Nº{registro_id}.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Documentos(bot))
