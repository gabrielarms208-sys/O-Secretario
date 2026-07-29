from datetime import date

import discord
from discord.ext import commands

import config
import db
import roblox_api
import roles_sync


class Promocoes(commands.Cog):
    """Escuta mudanças de cargo no servidor Principal. Quando um cargo de
    patente (definido em PATENTES no .env) é adicionado a alguém, grava
    isso como uma promoção e sincroniza posto/organizações/honrarias da
    ficha a partir dos cargos atuais dele. Se for a primeira patente da
    lista (ex: 'Recruta'), também define a data de entrada oficial."""

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
        if cargos_antes == cargos_depois:
            return

        cargos_rastreados = set(config.PATENTES) | set(config.ORGANIZACOES) | set(config.HONRARIAS)
        mudou_algo_relevante = (cargos_antes ^ cargos_depois) & cargos_rastreados
        if not mudou_algo_relevante:
            return

        novos_cargos = cargos_depois - cargos_antes
        cargo_de_patente = next((c for c in novos_cargos if c in config.PATENTES), None)

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

        hoje = date.today()

        if cargo_de_patente:
            # Se está recebendo a PRIMEIRA patente da lista (ex: "Recruta")
            # e a ficha atual dele estava marcada como Reserva R/2, entende
            # que é reinício de carreira: arquiva tudo que ele tinha antes
            # (ficha, formações, histórico de promoções) e começa do zero.
            if cargo_de_patente == config.PATENTES[0]:
                ficha_atual = await db.buscar_ficha(militar_id)
                if ficha_atual and ficha_atual["situacao"] == config.SITUACAO_RESERVA_R2:
                    await db.arquivar_e_resetar_ficha(militar_id, motivo="reinicio-carreira-pos-r2")

            await db.registrar_promocao(militar_id, cargo_de_patente, hoje, origem="auto-cargo")

        # sincroniza posto + organizações + honrarias a partir do conjunto
        # completo de cargos atuais (cobre tanto ganhar quanto perder cargo)
        campos = roles_sync.montar_campos_ficha(cargos_depois)
        if cargo_de_patente:
            campos["ultima_promocao"] = hoje.isoformat()
        await db.upsert_ficha(militar_id, campos)

        # se é a primeira patente da lista, define/atualiza a data de
        # entrada oficial (também cobre o caso de reinício pós-R/2,
        # já que o histórico de promoções foi zerado acima)
        if cargo_de_patente == config.PATENTES[0]:
            primeira = await db.primeira_promocao(militar_id)
            if primeira and primeira["patente"] == cargo_de_patente:
                await db.upsert_ficha(militar_id, {"data_entrada": hoje.isoformat()})


async def setup(bot: commands.Bot):
    await bot.add_cog(Promocoes(bot))
