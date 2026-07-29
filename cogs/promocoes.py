from datetime import date

import discord
from discord.ext import commands

import config
import db
import roblox_api


class Promocoes(commands.Cog):
    """Escuta mudanças de cargo no servidor Principal. Quando um cargo de
    patente (definido em PATENTES no .env) é adicionado a alguém, grava
    isso como uma promoção. Se for a primeira patente da lista (ex:
    'Recruta'), também define a data de entrada oficial na ficha."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.guild.id != config.GUILD_ID_PRINCIPAL:
            return
        if not config.PATENTES:
            return

        cargos_antes = {r.name for r in before.roles}
        cargos_depois = {r.name for r in after.roles}
        novos_cargos = cargos_depois - cargos_antes

        for nome_cargo in novos_cargos:
            if nome_cargo not in config.PATENTES:
                continue

            # O Rover, no servidor de vocês, usa o nickname do Discord como
            # o próprio username do Roblox (sem prefixo de patente ou outro
            # texto junto) — então é só pegar o display_name direto.
            roblox_username = after.display_name.strip()

            militar = await db.buscar_militar_por_username(roblox_username)
            if militar:
                militar_id = militar["id"]
            else:
                roblox_id = await roblox_api.resolver_id(roblox_username)
                militar_id = await db.upsert_militar(
                    roblox_id=roblox_id, roblox_username=roblox_username, discord_id=after.id
                )

            # Se está recebendo a PRIMEIRA patente da lista (ex: "Recruta")
            # e a ficha atual dele estava marcada como Reserva R/2, entende
            # que é reinício de carreira: arquiva tudo que ele tinha antes
            # (ficha, formações, histórico de promoções) e começa do zero.
            if nome_cargo == config.PATENTES[0]:
                ficha_atual = await db.buscar_ficha(militar_id)
                if ficha_atual and ficha_atual["situacao"] == config.SITUACAO_RESERVA_R2:
                    await db.arquivar_e_resetar_ficha(militar_id, motivo="reinicio-carreira-pos-r2")

            hoje = date.today()
            await db.registrar_promocao(militar_id, nome_cargo, hoje, origem="auto-cargo")
            await db.upsert_ficha(militar_id, {"posto": nome_cargo, "ultima_promocao": hoje.isoformat()})

            # se é a primeira patente da lista, define/atualiza a data de
            # entrada oficial (também cobre o caso de reinício pós-R/2,
            # já que o histórico de promoções foi zerado acima)
            if nome_cargo == config.PATENTES[0]:
                primeira = await db.primeira_promocao(militar_id)
                if primeira and primeira["patente"] == nome_cargo:
                    await db.upsert_ficha(militar_id, {"data_entrada": hoje.isoformat()})


async def setup(bot: commands.Bot):
    await bot.add_cog(Promocoes(bot))
