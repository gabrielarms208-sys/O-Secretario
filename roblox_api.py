"""
Cliente mínimo da API pública do Roblox. Não precisa de chave nem login.

Usamos só pra uma coisa: converter um username em ID numérico estável
(o ID nunca muda mesmo se a pessoa trocar de nome depois — é por isso
que o schema usa roblox_id como chave, e não o username).
"""
import aiohttp

_URL_USERNAMES = "https://users.roblox.com/v1/usernames/users"
_URL_THUMBNAIL = "https://thumbnails.roblox.com/v1/users/avatar-headshot"

# A API aceita até 100 usernames por chamada — lotes maiores que isso
# são divididos automaticamente.
_TAMANHO_LOTE = 100


async def resolver_ids(usernames: list[str]) -> dict[str, int | None]:
    """Recebe uma lista de usernames e devolve um dict {username: id}.
    Se algum username não existir (conta deletada, digitado errado etc.),
    o valor vem como None em vez de quebrar o lote inteiro."""
    resultado: dict[str, int | None] = {u: None for u in usernames}

    async with aiohttp.ClientSession() as session:
        for i in range(0, len(usernames), _TAMANHO_LOTE):
            lote = usernames[i : i + _TAMANHO_LOTE]
            payload = {"usernames": lote, "excludeBannedUsers": False}
            async with session.post(_URL_USERNAMES, json=payload) as resp:
                if resp.status != 200:
                    continue
                dados = await resp.json()
                for item in dados.get("data", []):
                    # a API devolve "requestedUsername" com a grafia exata
                    # que foi mandada, então usamos ela pra bater com o dict
                    resultado[item["requestedUsername"]] = item["id"]

    return resultado


async def resolver_id(username: str) -> int | None:
    """Versão pra um único username (usada nos comandos manuais, tipo
    /ficha atualizar, quando só um militar precisa ser resolvido)."""
    resultado = await resolver_ids([username])
    return resultado.get(username)


async def avatar_headshot_url(roblox_id: int, tamanho: str = "150x150") -> str | None:
    """Devolve a URL da foto de perfil (headshot) do Roblox pra usar como
    thumbnail na ficha. Devolve None se o roblox_id não tiver sido
    resolvido ainda ou se a API falhar."""
    if not roblox_id:
        return None

    params = {"userIds": str(roblox_id), "size": tamanho, "format": "Png", "isCircular": "false"}
    async with aiohttp.ClientSession() as session:
        async with session.get(_URL_THUMBNAIL, params=params) as resp:
            if resp.status != 200:
                return None
            dados = await resp.json()
            itens = dados.get("data", [])
            if itens and itens[0].get("state") == "Completed":
                return itens[0].get("imageUrl")
    return None
