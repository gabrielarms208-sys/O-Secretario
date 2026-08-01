import discord
from discord import app_commands
from discord.ext import commands

import config
import db
import roblox_api
import roles_sync
from import_parser import parse_ficha


def _formatar_data_br(iso: str | None) -> str:
    """'2026-07-29' -> '29/07/2026', pra ficar mais legível no embed."""
    if not iso:
        return "—"
    partes = iso.split("-")
    return f"{partes[2]}/{partes[1]}/{partes[0]}" if len(partes) == 3 else iso


def _cor_por_situacao(situacao: str | None) -> discord.Color:
    if situacao == config.SITUACAO_RESERVA_R1:
        return discord.Color.gold()
    if situacao == config.SITUACAO_RESERVA_R2:
        return discord.Color.dark_grey()
    if situacao in (None, "Ativa"):
        return discord.Color.dark_green()
    return discord.Color.dark_red()


# ---------- Autocomplete ----------
# Sugere, enquanto a pessoa digita, só usernames que já existem no banco —
# evita erro de digitação, que era a causa do "militar não encontrado".

async def militar_autocomplete(interaction: discord.Interaction, current: str):
    nomes = await db.militares_autocomplete(current)
    return [app_commands.Choice(name=n, value=n) for n in nomes]


async def _montar_embed_ficha(militar, ficha) -> tuple[discord.Embed, list, bool]:
    """Monta o embed "bonito" da ficha (emoji, cor por situação, thumbnail
    do Roblox, campos) — usado tanto por `/ficha ver` quanto por
    `/ficha criar`, pra que os dois fiquem sempre visualmente idênticos.
    Retorna (embed, formações ativas, se deve mostrar o botão "ver todas")."""
    situacao = ficha["situacao"] or "Ativa"
    embed = discord.Embed(
        title=f"🎖️  {militar['roblox_username']}",
        description=f"### {ficha['posto'] or 'Sem posto definido'}",
        color=_cor_por_situacao(situacao),
    )

    if militar["roblox_id"]:
        avatar = await roblox_api.avatar_headshot_url(militar["roblox_id"])
        if avatar:
            embed.set_thumbnail(url=avatar)

    embed.add_field(name="📋 Situação", value=situacao, inline=True)
    embed.add_field(name="⚔️ Arma", value=ficha["arma"] or "—", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)  # espaçador pra alinhar 3 colunas
    embed.add_field(name="📅 Entrada", value=_formatar_data_br(ficha["data_entrada"]), inline=True)
    embed.add_field(name="⭐ Última promoção", value=_formatar_data_br(ficha["ultima_promocao"]), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(
        name="🏛️ Organizações Militares",
        value=(ficha["organizacoes"] or "—").replace(";", "\n•").lstrip("•") or "—",
        inline=False,
    )
    embed.add_field(
        name="🏅 Honrarias",
        value=(ficha["honrarias"] or "—").replace(";", "\n•").lstrip("•") or "—",
        inline=False,
    )
    if ficha["feitos"]:
        embed.add_field(
            name="📜 Feitos",
            value=ficha["feitos"].replace(";", "\n•").lstrip("•"),
            inline=False,
        )

    formacoes = await db.formacoes_por_militar(militar["id"])
    ativas = [f for f in formacoes if f["status"] == "ativo"]
    mostrar_botao = False
    if ativas:
        LIMITE = 8
        linhas = [f"• {f['curso_nome']} (Nº{f['numero_sequencial']})" for f in ativas[:LIMITE]]
        if len(ativas) > LIMITE:
            linhas.append(f"…e mais {len(ativas) - LIMITE}")
            mostrar_botao = True
        embed.add_field(name=f"🎓 Formações ({len(ativas)})", value="\n".join(linhas), inline=False)
    else:
        embed.add_field(name="🎓 Formações", value="Nenhuma formação registrada ainda.", inline=False)

    # `ficha_completa` só é preenchido pelo importador de texto do fórum
    # (0 = faltou campo, 1 = ok). Pra fichas geradas via `/ficha criar` ou
    # `/ficha sincronizar` (a partir dos cargos), essa coluna nunca é
    # escrita e fica None — nesse caso o aviso de "incompleta" não se
    # aplica, então só mostramos quando o valor for explicitamente 0.
    if ficha["ficha_completa"] == 0:
        embed.set_footer(text="⚠️ Ficha importada incompleta — falta revisar alguns campos.")
    else:
        embed.set_footer(text="Vila Militar — Secretaria Geral do Exército")

    return embed, ativas, mostrar_botao


class VerTodasFormacoesView(discord.ui.View):
    """Botão que aparece no `/ficha ver` quando o militar tem mais
    formações do que cabe no embed principal — abre a lista completa numa
    mensagem privada (só quem clicou vê), sem poluir o canal."""

    def __init__(self, militar_id: int, roblox_username: str):
        super().__init__(timeout=300)  # some sozinho depois de 5min pra não ficar um botão morto
        self.militar_id = militar_id
        self.roblox_username = roblox_username

    @discord.ui.button(label="Ver todas as formações", style=discord.ButtonStyle.secondary, emoji="🎓")
    async def ver_todas(self, interaction: discord.Interaction, button: discord.ui.Button):
        formacoes = await db.formacoes_por_militar(self.militar_id)
        ativas = [f for f in formacoes if f["status"] == "ativo"]
        if not ativas:
            await interaction.response.send_message("Nenhuma formação registrada.", ephemeral=True)
            return

        linhas = [f"• {f['curso_nome']} (Nº{f['numero_sequencial']})" for f in ativas]

        # o Discord limita cada embed a ~4096 caracteres de descrição e no
        # máximo 10 embeds por mensagem — divide em blocos pra caber
        # tranquilamente qualquer quantidade razoável de formações
        blocos, atual = [], ""
        for linha in linhas:
            if len(atual) + len(linha) + 1 > 3900:
                blocos.append(atual)
                atual = ""
            atual += linha + "\n"
        if atual:
            blocos.append(atual)

        embeds = []
        for i, bloco in enumerate(blocos[:10]):
            embed = discord.Embed(
                title=f"🎓 Todas as formações de {self.roblox_username} ({len(ativas)})" if i == 0 else None,
                description=bloco,
            )
            embeds.append(embed)

        await interaction.response.send_message(embeds=embeds, ephemeral=True)


class Ficha(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    ficha_group = app_commands.Group(name="ficha", description="Ficha militar dos membros")

    @ficha_group.command(name="ver", description="Mostra a ficha militar de um membro")
    @app_commands.describe(roblox_username="Nome do militar no Roblox")
    @app_commands.autocomplete(roblox_username=militar_autocomplete)
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

        embed, ativas, mostrar_botao = await _montar_embed_ficha(militar, ficha)

        if mostrar_botao:
            view = VerTodasFormacoesView(militar["id"], militar["roblox_username"])
            await interaction.response.send_message(embed=embed, view=view)
        else:
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
    @app_commands.autocomplete(roblox_username=militar_autocomplete)
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

    @ficha_group.command(name="sincronizar", description="Puxa posto/OM/honrarias direto dos cargos atuais do membro no servidor Principal")
    @app_commands.describe(membro="O membro no servidor (menção @)")
    async def sincronizar(self, interaction: discord.Interaction, membro: discord.Member):
        if membro.guild.id != config.GUILD_ID_PRINCIPAL:
            await interaction.response.send_message(
                "Esse comando só funciona rodado no servidor Principal.", ephemeral=True
            )
            return

        roblox_username = membro.display_name.strip()
        cargos = {r.name for r in membro.roles}
        campos = roles_sync.montar_campos_ficha(cargos)

        if not campos.get("posto"):
            await interaction.response.send_message(
                f"{membro.mention} não tem nenhum cargo de patente reconhecido (configurado em `PATENTES`) — nada pra sincronizar.",
                ephemeral=True,
            )
            return

        militar = await db.buscar_militar_por_username(roblox_username)
        if militar:
            militar_id = militar["id"]
        else:
            roblox_id = await roblox_api.resolver_id(roblox_username)
            militar_id = await db.upsert_militar(roblox_id=roblox_id, roblox_username=roblox_username, discord_id=membro.id)

        await db.upsert_ficha(militar_id, campos)
        await interaction.response.send_message(
            f"`{roblox_username}` sincronizado a partir dos cargos atuais: **{campos['posto']}**. ✅"
        )

    @ficha_group.command(
        name="criar",
        description="[Admin] Gera a ficha a partir dos cargos atuais e posta/atualiza no fórum de fichas",
    )
    @app_commands.describe(membro="O membro no servidor (menção @)")
    @app_commands.checks.has_permissions(administrator=True)
    async def criar(self, interaction: discord.Interaction, membro: discord.Member):
        if membro.guild.id != config.GUILD_ID_PRINCIPAL:
            await interaction.response.send_message(
                "Esse comando só funciona rodado no servidor Principal.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)

        roblox_username = membro.display_name.strip()
        cargos = {r.name for r in membro.roles}
        campos = roles_sync.montar_campos_ficha(cargos)

        if not campos.get("posto"):
            await interaction.followup.send(
                f"{membro.mention} não tem nenhum cargo de patente reconhecido (configurado em `PATENTES`) — "
                f"nada pra gerar."
            )
            return

        militar = await db.buscar_militar_por_username(roblox_username)
        if militar:
            militar_id = militar["id"]
        else:
            roblox_id = await roblox_api.resolver_id(roblox_username)
            militar_id = await db.upsert_militar(roblox_id=roblox_id, roblox_username=roblox_username, discord_id=membro.id)

        await db.upsert_ficha(militar_id, campos)
        ficha = await db.buscar_ficha(militar_id)
        # re-busca o militar pra pegar roblox_id/username já resolvidos
        # (importante no caso de ter acabado de ser criado acima)
        militar = await db.buscar_militar_por_username(roblox_username)

        canal = self.bot.get_channel(config.CHANNEL_ID_FICHAS)
        if canal is None:
            await interaction.followup.send(
                f"Ficha de `{roblox_username}` salva no banco (Posto: **{campos['posto']}**), mas não encontrei "
                f"o canal de fichas configurado (CHANNEL_ID_FICHAS) pra postar/atualizar a thread — ID errado "
                f"ou o bot não tem permissão de Ver Canal nele."
            )
            return

        embed, _, _ = await _montar_embed_ficha(militar, ficha)

        # se já tiver uma thread salva de uma vez anterior, tenta reaproveitar
        # (edita o post existente) em vez de criar uma duplicada
        thread_existente = None
        if ficha["thread_id"]:
            thread_existente = self.bot.get_channel(ficha["thread_id"])
            if thread_existente is None:
                try:
                    thread_existente = await membro.guild.fetch_channel(ficha["thread_id"])
                except (discord.NotFound, discord.Forbidden):
                    thread_existente = None

        mensagem_existente = None
        if thread_existente is not None:
            try:
                mensagem_existente = await thread_existente.fetch_message(ficha["thread_message_id"])
            except (discord.NotFound, discord.Forbidden):
                mensagem_existente = None

        if thread_existente is not None and mensagem_existente is not None:
            await mensagem_existente.edit(embed=embed)
            if thread_existente.name != roblox_username:
                try:
                    await thread_existente.edit(name=roblox_username)
                except discord.HTTPException:
                    pass
            await db.salvar_thread_ficha(militar_id, thread_existente.id, mensagem_existente.id)
            await interaction.followup.send(
                f"Ficha de `{roblox_username}` **atualizada** na thread existente: {thread_existente.jump_url} ✅"
            )
        else:
            resultado = await canal.create_thread(name=roblox_username, embed=embed)
            await db.salvar_thread_ficha(militar_id, resultado.thread.id, resultado.message.id)
            await interaction.followup.send(
                f"Ficha de `{roblox_username}` **criada** numa thread nova: {resultado.thread.jump_url} ✅"
            )

    @ficha_group.command(name="sincronizar_todos", description="[Admin] Puxa posto/OM/honrarias de TODO MUNDO no servidor Principal a partir dos cargos atuais")
    @app_commands.checks.has_permissions(administrator=True)
    async def sincronizar_todos(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        guild = self.bot.get_guild(config.GUILD_ID_PRINCIPAL)
        if guild is None:
            await interaction.followup.send("Não encontrei o servidor Principal configurado (GUILD_ID_PRINCIPAL).")
            return

        membros = [m for m in guild.members if not m.bot]

        # resolve em lote só os usernames que ainda não existem no banco,
        # pra não bater na API do Roblox um por um (mais rápido e mais
        # gentil com o rate limit deles)
        a_resolver = []
        for m in membros:
            username = m.display_name.strip()
            if not await db.buscar_militar_por_username(username):
                a_resolver.append(username)
        ids_resolvidos = await roblox_api.resolver_ids(a_resolver) if a_resolver else {}

        sincronizados, sem_patente = 0, 0
        for m in membros:
            roblox_username = m.display_name.strip()
            cargos = {r.name for r in m.roles}
            campos = roles_sync.montar_campos_ficha(cargos)

            if not campos.get("posto"):
                sem_patente += 1
                continue

            militar = await db.buscar_militar_por_username(roblox_username)
            if militar:
                militar_id = militar["id"]
            else:
                roblox_id = ids_resolvidos.get(roblox_username)
                militar_id = await db.upsert_militar(
                    roblox_id=roblox_id, roblox_username=roblox_username, discord_id=m.id
                )

            await db.upsert_ficha(militar_id, campos)
            sincronizados += 1

        await interaction.followup.send(
            f"Sincronização concluída: {sincronizados} fichas atualizadas a partir dos cargos atuais, "
            f"{sem_patente} membros ignorados (sem cargo de patente reconhecido).\n"
            f"⚠️ Isso só preenche posto/organizações/honrarias — data de entrada e última promoção continuam "
            f"vindo do histórico de promoções (automático quando o cargo mudar dali pra frente, ou `/ficha atualizar` pra ajustar manualmente uma vez)."
        )

    @ficha_group.command(name="reserva", description="Marca um militar como Reserva R/1 ou R/2")
    @app_commands.describe(roblox_username="Nome do militar no Roblox", tipo="R/1 (pode voltar) ou R/2 (carreira encerrada)")
    @app_commands.choices(tipo=[
        app_commands.Choice(name="R/1 — pode retornar", value="R1"),
        app_commands.Choice(name="R/2 — carreira encerrada", value="R2"),
    ])
    @app_commands.autocomplete(roblox_username=militar_autocomplete)
    async def reserva(self, interaction: discord.Interaction, roblox_username: str, tipo: app_commands.Choice[str]):
        militar = await db.buscar_militar_por_username(roblox_username)
        if not militar:
            await interaction.response.send_message("Militar não encontrado.", ephemeral=True)
            return

        situacao = config.SITUACAO_RESERVA_R1 if tipo.value == "R1" else config.SITUACAO_RESERVA_R2
        await db.upsert_ficha(militar["id"], {"situacao": situacao})
        await interaction.response.send_message(f"`{roblox_username}` marcado como **{situacao}**. ✅")

    @ficha_group.command(name="historico", description="Mostra carreiras antigas arquivadas de um militar (pós-R/2)")
    @app_commands.autocomplete(roblox_username=militar_autocomplete)
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
            await interaction.followup.send(
                "Não encontrei o canal de fichas configurado (CHANNEL_ID_FICHAS) — ID errado ou o bot não tem "
                "permissão de Ver Canal nele."
            )
            return

        importadas, incompletas, puladas, geradas_pelo_bot = 0, 0, 0, 0
        async for thread in canal.archived_threads(limit=None):
            importadas, incompletas, puladas, geradas_pelo_bot = await self._importar_thread(
                thread, importadas, incompletas, puladas, geradas_pelo_bot
            )
        for thread in canal.threads:
            importadas, incompletas, puladas, geradas_pelo_bot = await self._importar_thread(
                thread, importadas, incompletas, puladas, geradas_pelo_bot
            )

        mensagem = (
            f"Importação concluída: {importadas} fichas processadas, {incompletas} marcadas como incompletas "
            f"(faltando campos — precisam de revisão manual)."
        )
        if geradas_pelo_bot:
            mensagem += (
                f"\n{geradas_pelo_bot} thread(s) ignorada(s) por já terem sido geradas pelo próprio bot "
                f"(`/ficha criar`) — o banco já é a fonte de verdade pra elas, não precisam ser relidas."
            )
        if puladas:
            mensagem += (
                f"\n⚠️ {puladas} thread(s) pulada(s) — primeira mensagem sem texto e sem embed legível "
                f"(ex: só imagem/anexo, sem conteúdo pra extrair a ficha)."
            )
        await interaction.followup.send(mensagem)

    @staticmethod
    def _extrair_texto_mensagem(msg: discord.Message) -> str:
        """As fichas do SGEx costumam ser postadas via webhook como EMBED
        (a barra colorida na lateral) em vez de texto puro — nesse caso
        `msg.content` vem vazio. Concatena título, descrição e campos de
        todos os embeds da mensagem como texto pra alimentar o parser."""
        partes = [msg.content] if msg.content else []
        for embed in msg.embeds:
            if embed.title:
                partes.append(embed.title)
            if embed.description:
                partes.append(embed.description)
            for field in embed.fields:
                if field.name:
                    partes.append(field.name)
                if field.value:
                    partes.append(field.value)
        return "\n".join(partes)

    async def _importar_thread(
        self, thread: discord.Thread, importadas: int, incompletas: int, puladas: int = 0, geradas_pelo_bot: int = 0
    ):
        primeira_msg = None
        async for msg in thread.history(limit=1, oldest_first=True):
            primeira_msg = msg
        if primeira_msg is None:
            return importadas, incompletas, puladas, geradas_pelo_bot

        if primeira_msg.author.id == self.bot.user.id:
            # post gerado pelo próprio bot via `/ficha criar` — o banco já é
            # a fonte de verdade pra essa ficha, não precisa reler por regex
            # (e evita sobrescrever a ficha com o que o próprio bot postou)
            geradas_pelo_bot += 1
            return importadas, incompletas, puladas, geradas_pelo_bot

        texto = self._extrair_texto_mensagem(primeira_msg)
        if not texto:
            puladas += 1
            return importadas, incompletas, puladas, geradas_pelo_bot

        # o nome do militar normalmente é o título da thread ou a primeira
        # linha em negrito/link do corpo — aqui usamos o título da thread.
        roblox_username = thread.name.split(" - ")[0].strip()
        campos = parse_ficha(texto)

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
        return importadas, incompletas, puladas, geradas_pelo_bot


async def setup(bot: commands.Bot):
    await bot.add_cog(Ficha(bot))
