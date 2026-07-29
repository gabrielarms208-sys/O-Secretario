import asyncio
import logging

import discord
from discord.ext import commands

import config
import db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ficha-militar-bot")

intents = discord.Intents.default()
intents.members = True          # necessário pra detectar mudança de cargo (promoções)
intents.message_content = True  # necessário pra ler o texto dos posts do fórum na importação

bot = commands.Bot(command_prefix="!", intents=intents)

COGS = ["cogs.ficha", "cogs.formacoes", "cogs.promocoes", "cogs.documentos"]


@bot.event
async def on_ready():
    log.info(f"Conectado como {bot.user} (id: {bot.user.id})")
    log.info(f"Em {len(bot.guilds)} servidor(es): {[g.name for g in bot.guilds]}")
    synced = await bot.tree.sync()
    log.info(f"{len(synced)} slash commands sincronizados.")


async def main():
    config.validar_config()
    await db.iniciar_banco()

    async with bot:
        for cog in COGS:
            await bot.load_extension(cog)
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
