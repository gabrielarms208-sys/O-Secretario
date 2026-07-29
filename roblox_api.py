"""
Cliente mínimo da API pública do Roblox. Não precisa de chave nem login.

Usamos só pra uma coisa: converter um username em ID numérico estável
(o ID nunca muda mesmo se a pessoa trocar de nome depois — é por isso
que o schema usa roblox_id como chave, e não o username).
"""
import aiohttp

_URL_USERNAMES = "https://users.roblox.com/v1/usernames/users"

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
