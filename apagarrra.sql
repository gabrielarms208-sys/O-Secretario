-- ============================================================
-- SCHEMA - Bot de Ficha Militar + Formações
-- ============================================================

-- Um registro por militar. Chave estável = roblox_id (nunca muda,
-- mesmo se o username do Roblox for trocado depois).
CREATE TABLE IF NOT EXISTS militares (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    roblox_id       BIGINT UNIQUE,             -- ID numérico do Roblox (estável). NULL = ainda não resolvido pela API
    roblox_username TEXT NOT NULL,             -- username atual (pode mudar, atualizado quando detectado)
    discord_id      BIGINT UNIQUE,             -- ID do Discord, se conhecido/linkado
    criado_em       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Ficha militar em si (1 para 1 com militar). Campos "soltos" que
-- podem ser atualizados via upsert sem mexer no resto.
CREATE TABLE IF NOT EXISTS fichas (
    militar_id           INTEGER PRIMARY KEY REFERENCES militares(id),
    posto                TEXT,               -- ex: "Comandante do Exército"
    data_entrada          DATE,               -- data oficial de alistamento (1º cargo Recruta)
    ultima_promocao        DATE,
    situacao              TEXT DEFAULT 'Ativa', -- Ativa, Licenciado, Reformado, Baixado...
    arma                  TEXT,               -- ex: "Infantaria"
    organizacoes          TEXT,               -- lista simples (JSON ou separado por ;) das OMs
    honrarias              TEXT,               -- lista simples, preenchida manualmente (não sincroniza com o fórum de medalhas)
    fonte_import          TEXT,               -- 'manual' ou 'importado-forum' (rastreio de origem)
    ficha_completa         BOOLEAN DEFAULT 1,  -- false = importada faltando campos, precisa revisão
    atualizado_em          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Histórico de promoções (permite reconstruir a linha do tempo de patente)
CREATE TABLE IF NOT EXISTS historico_promocoes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    militar_id   INTEGER REFERENCES militares(id),
    patente      TEXT NOT NULL,
    data         DATE NOT NULL,
    origem       TEXT DEFAULT 'auto-cargo'  -- 'auto-cargo' (detectado por role) ou 'manual'
);

-- Catálogo de cursos/estágios (Paraquedista, Blindados, Ações de Comando...)
CREATE TABLE IF NOT EXISTS cursos (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    nome   TEXT UNIQUE NOT NULL
);

-- Edições/turmas de cada curso. Texto livre pro "apelido" da edição
-- (ex: "13ª Edição (C DoMPSA)", "Transferência do QEB").
CREATE TABLE IF NOT EXISTS edicoes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    curso_id     INTEGER REFERENCES cursos(id),
    numero       TEXT,     -- "1", "13", "Transferência do QEB" etc — texto livre
    apelido      TEXT,     -- ex: "(C DoMPSA)", "(AMAN - Estágio)", nome de comandante
    UNIQUE(curso_id, numero)
);

-- Formações concluídas. status permite soft-delete (cassação) sem
-- perder o histórico nem o número sequencial.
CREATE TABLE IF NOT EXISTS formacoes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    militar_id      INTEGER REFERENCES militares(id),
    curso_id        INTEGER REFERENCES cursos(id),
    edicao_id       INTEGER REFERENCES edicoes(id),
    numero_sequencial INTEGER,   -- ex: "Nº47" dentro do curso
    data            DATE,
    status          TEXT DEFAULT 'ativo',  -- 'ativo' ou 'cassado'
    data_cassacao   DATE,
    fonte_import    TEXT,        -- 'manual' ou 'importado-forum'
    criado_em       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Apelidos/siglas de um curso (ex: "PQDT" e "Paraquedista" apontando pro
-- mesmo curso "Curso Básico Paraquedista"). Cadastrado manualmente via
-- `/formacao apelido adicionar`. A sigla "oficial" (ex: COS) já é
-- reconhecida automaticamente sem precisar cadastrar aqui — essa tabela
-- é só pros apelidos que não dá pra deduzir do nome.
CREATE TABLE IF NOT EXISTS curso_apelidos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    curso_id  INTEGER REFERENCES cursos(id),
    apelido   TEXT NOT NULL,
    UNIQUE(apelido COLLATE NOCASE)
);

CREATE INDEX IF NOT EXISTS idx_curso_apelidos_curso ON curso_apelidos(curso_id);

-- Índices pra busca rápida (o caso de uso mais comum: achar por username)
CREATE INDEX IF NOT EXISTS idx_militares_username ON militares(roblox_username);
CREATE INDEX IF NOT EXISTS idx_formacoes_militar ON formacoes(militar_id);
CREATE INDEX IF NOT EXISTS idx_formacoes_curso_edicao ON formacoes(curso_id, edicao_id);

-- ============================================================
-- Sistema de reserva (R/1 e R/2)
-- ============================================================

-- Quando um militar em Reserva R/2 volta como Recruta (nova carreira),
-- a ficha/formações/histórico de promoções antigos são arquivados aqui
-- (snapshot em JSON) em vez de apagados, e depois removidos das tabelas
-- "ativas" pra ele começar do zero de fato.
CREATE TABLE IF NOT EXISTS historico_fichas_arquivadas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    militar_id      INTEGER REFERENCES militares(id),
    motivo          TEXT,               -- ex: 'reinicio-carreira-pos-r2'
    dados_ficha     TEXT,               -- snapshot JSON da linha de `fichas`
    dados_formacoes TEXT,               -- snapshot JSON das linhas de `formacoes`
    dados_promocoes TEXT,               -- snapshot JSON das linhas de `historico_promocoes`
    arquivado_em    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_arquivo_militar ON historico_fichas_arquivadas(militar_id);

-- ============================================================
-- Documentos das unidades (regulamentos, decretos, ordens de serviço)
-- ============================================================

CREATE TABLE IF NOT EXISTS documentos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    unidade     TEXT,       -- ex: "Brigada de Infantaria Paraquedista", "COEX"
    tipo        TEXT,       -- ex: "Regulamento Interno", "Decreto", "Ordem de Serviço"
    numero      TEXT,       -- ex: "15" — texto livre pra aceitar formatos variados
    titulo      TEXT,       -- título/descrição livre do documento
    link        TEXT NOT NULL,
    criado_em   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_documentos_busca ON documentos(unidade, tipo, numero);

