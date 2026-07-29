"""
Funções puras (sem falar com o Discord nem com o banco) que olham pro
conjunto de cargos de um membro e devolvem o que a ficha dele deveria ter.
Usado tanto pelo listener automático (promocoes.py, quando um cargo muda)
quanto pelo comando manual `/ficha sincronizar` (ficha.py, sob demanda).
Manter essa lógica num lugar só evita os dois ficarem desalinhados.
"""
import config


def calcular_posto(nomes_dos_cargos: set[str]) -> str | None:
    """Devolve a patente de maior hierarquia que o membro tem, olhando
    `config.PATENTES` do fim pro começo (a lista é da mais baixa pra mais
    alta). Se o membro tiver Recruta E General ao mesmo tempo por algum
    motivo, prevalece General."""
    for patente in reversed(config.PATENTES):
        if patente in nomes_dos_cargos:
            return patente
    return None


def calcular_organizacoes(nomes_dos_cargos: set[str]) -> list[str]:
    """Todos os cargos de OM (config.ORGANIZACOES) que o membro tem."""
    return [om for om in config.ORGANIZACOES if om in nomes_dos_cargos]


def calcular_honrarias(nomes_dos_cargos: set[str]) -> list[str]:
    """Todos os cargos de honraria/medalha (config.HONRARIAS) que o membro tem."""
    return [h for h in config.HONRARIAS if h in nomes_dos_cargos]


def montar_campos_ficha(nomes_dos_cargos: set[str]) -> dict:
    """Monta o dict pronto pra passar em `db.upsert_ficha`, só com os
    campos que a gente consegue deduzir dos cargos atuais. Campos que
    dependem de listas vazias na config (ORGANIZACOES/HONRARIAS não
    configuradas) simplesmente não entram no dict, pra não sobrescrever
    o que já foi preenchido manualmente com um vazio."""
    campos = {}

    posto = calcular_posto(nomes_dos_cargos)
    if posto:
        campos["posto"] = posto

    if config.ORGANIZACOES:
        campos["organizacoes"] = "; ".join(calcular_organizacoes(nomes_dos_cargos))

    if config.HONRARIAS:
        campos["honrarias"] = "; ".join(calcular_honrarias(nomes_dos_cargos))

    return campos
