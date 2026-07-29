# Bot de Ficha Militar + Formações

Bot dedicado que mantém a ficha militar dos membros e o histórico de
formações em cursos/estágios do Exército, lendo dados de 3 servidores
de Discord (Principal, SGEx e Decex).

## O que ele faz

- `/ficha ver <username>` — mostra a ficha militar completa.
- `/ficha atualizar <username> ...` — cria ou atualiza campos da ficha (upsert).
- `/ficha sincronizar <@membro>` — puxa posto/organizações/honrarias direto dos cargos atuais do membro no servidor Principal (sem digitar nada manual).
- `/ficha sincronizar_todos` *(admin)* — faz o mesmo de uma vez pra todo mundo do servidor Principal.
- `/ficha reserva <username> tipo:R1|R2` — marca a situação de reserva.
- `/ficha historico <username>` — mostra carreiras antigas arquivadas (pós-R/2).
- `/ficha importar` *(admin)* — lê o fórum `ficha-militar` do SGEx e importa/atualiza tudo.
- `/formacao adicionar <username> curso edicao data` — registra uma formação.
- `/formacao remover <username> curso edicao` — cassa (soft delete, mantém no histórico).
- `/formacao consultar <username>` — lista as formações de um militar.
- `/formacao relatorio curso edicao` — lista todos os formados de uma turma.
- `/formacao importar` *(admin)* — lê os fóruns de Cursos/Estágios/Academias do Decex.
- `/formacao apelido adicionar <curso> <apelido>` *(admin)* — associa um apelido/sigla extra a um curso já cadastrado.
- `/formacao apelido listar <curso>` — mostra a sigla automática + os apelidos manuais de um curso.
- `/documento adicionar` *(admin)* — cadastra um regulamento/decreto/ordem de serviço.
- `/documento buscar <termo>` — busca e devolve o link do documento.
- `/documento remover <id>` *(admin)* — remove um documento cadastrado.
- Detecta automaticamente mudanças de cargo/patente no servidor Principal e grava no histórico de promoções.
- **Reserva R/2 → volta como Recruta**: se um militar marcado como Reserva R/2 (carreira encerrada) recebe o cargo de Recruta de novo, o bot entende que é reinício de carreira — arquiva a ficha/formações/promoções antigas (consultáveis via `/ficha historico`) e começa um registro limpo automaticamente.

## Passo a passo pra colocar no ar

### 1. Criar a aplicação do bot
1. Acesse https://discord.com/developers/applications e clique em **New Application**.
2. Vá em **Bot** → **Reset Token** → copie o token (isso vai no `.env`, nunca compartilhe).
3. Em **Privileged Gateway Intents**, ative **Server Members Intent** e **Message Content Intent** (o bot precisa disso pra detectar promoções e ler os fóruns).
4. Em **OAuth2 → URL Generator**, marque escopo `bot` e `applications.commands`, e nas permissões marque pelo menos: Ver Canais, Enviar Mensagens, Usar Comandos de Barra, Ler Histórico de Mensagens.
5. Use o link gerado pra convidar o bot nos **3 servidores** (Principal, SGEx, Decex).

### 2. Configurar o projeto
```bash
pip install -r requirements.txt
cp .env.example .env
```
Preencha o `.env`:
- `DISCORD_TOKEN`: o token copiado no passo 1.
- `GUILD_ID_*`: ative o Modo Desenvolvedor no Discord (Configurações → Avançado) e copie o ID de cada servidor (botão direito → Copiar ID).
- `CHANNEL_ID_FICHAS`: ID do fórum `ficha-militar` no SGEx.
- `CHANNEL_ID_FORMACOES` + `CHANNEL_IDS_FORMACOES_EXTRA`: IDs dos fóruns de Cursos, Estágios e Academias no Decex (o primeiro vai sozinho, os outros dois separados por vírgula no campo EXTRA).
- `PATENTES`: lista de cargos de patente em ordem, exatamente como aparecem no servidor Principal.

O `.env` já vem preenchido com os IDs dos 3 servidores e dos 3 fóruns de formação que vocês passaram — só falta completar `DISCORD_TOKEN` e `PATENTES`.

### 3. Rodar localmente pra testar
```bash
python bot.py
```
O banco SQLite (`ficha_militar.db`) é criado automaticamente na primeira execução.

### 4. Deploy no Railway
Mesma lógica do bot de férias: suba esse projeto num repositório GitHub separado (ou pasta separada), crie um novo serviço no Railway a partir dele, e configure as mesmas variáveis do `.env` como variáveis de ambiente do serviço.

## Como o bot reconhece "Paraquedista" = "PQDT" = "Curso Básico Paraquedista"

Todo lugar que recebe um nome de curso digitado (`/formacao adicionar`, `remover`, `relatorio`, `apelido`) passa pela mesma busca, nessa ordem:

1. **Nome exato** cadastrado (sem diferenciar maiúscula/minúscula).
2. **Apelido cadastrado manualmente** (`/formacao apelido adicionar`).
3. **Sigla automática**: o bot monta a sigla a partir das iniciais das palavras do nome, ignorando "de/da/do/na/no/e/com" etc. — "Curso de Operações na Selva" vira **COS** sozinho, sem precisar cadastrar nada.
4. **"Contém"**: se o termo digitado aparece dentro do nome do curso (ou vice-versa) — "Montanha" bate em "Curso Básico de Montanha" automaticamente.

Isso cobre a maioria dos casos (Montanha, Selva/COS, Operações etc.) sem trabalho manual. **A única situação que precisa de `/formacao apelido`** é quando o apelido é uma abreviação de uma palavra só, não a sigla de várias — "PQDT" é abreviação de "Paraquedista", uma palavra só, então o bot não adivinha sozinho. Nesse caso, depois de cadastrar o curso como "Curso Básico Paraquedista", rode uma vez:
```
/formacao apelido adicionar curso:Curso Básico Paraquedista apelido:PQDT
/formacao apelido adicionar curso:Curso Básico Paraquedista apelido:Paraquedista
```
E dali em diante, `/formacao adicionar`, `remover` e `relatorio` aceitam `PQDT`, `Paraquedista` ou o nome completo, todos apontando pro mesmo curso.

⚠️ O casamento por "contém" é simples de propósito (sem lib de fuzzy match) — se dois cursos tiverem nomes muito parecidos e sobrepostos (ex: "Curso de Selva" e "Curso Avançado de Selva"), pode dar ambiguidade. Nesse caso, cadastre apelidos explícitos pros dois pra evitar confusão, ou digite o nome completo.

## Preenchimento automático da ficha (sem digitar tudo na mão)

Hoje o bot já pega **posto** e **última promoção** sozinho, sempre que o cargo de patente do membro muda no servidor Principal (`PATENTES` no `.env`).

Agora, se você preencher também `ORGANIZACOES` e `HONRARIAS` no `.env` (mesmo formato do `PATENTES`: nomes de cargo do Discord, separados por vírgula, e batendo EXATAMENTE com o nome do cargo), o bot passa a preencher esses dois campos sozinho também — toda vez que o cargo de OM ou de honraria de alguém mudar. Exemplo:

```
ORGANIZACOES=Brigada de Infantaria Paraquedista,Brigada de Cavalaria Blindada,COEX
HONRARIAS=Estrela de Bronze,Estrela de Prata,Cruz de Combate
```

Se deixar essas duas variáveis em branco, nada quebra — só continuam sendo preenchidas manualmente via `/ficha atualizar`, como já era antes.

**Pra sincronizar quem já está no servidor hoje** (sem esperar o cargo mudar de novo), use:
- `/ficha sincronizar @membro` — sincroniza uma pessoa.
- `/ficha sincronizar_todos` *(admin)* — sincroniza todo mundo do servidor Principal de uma vez. Só preenche posto/OM/honrarias; a data de entrada e a última promoção continuam vindo do histórico real de promoções (pra não inventar uma data errada pra quem já é antigo — ajuste essas duas manualmente uma vez com `/ficha atualizar` se precisar).

## Decisões de design tomadas nesta rodada

- **Reserva R/2 → volta como Recruta:** optei por **arquivar** (não apagar de vez) a ficha/formações/promoções antigas. Na prática funciona igual pro dia a dia (a ficha atual fica limpa, como se fosse nova), mas o histórico continua consultável via `/ficha historico`, caso precisem provar uma carreira antiga depois. Se realmente preferirem apagar sem guardar nada, é só me falar que eu tiro o arquivamento.
- **Documentos:** montei como cadastro manual (`/documento adicionar`), já que não tinha um canal/fórum organizado pra importar de uma vez. Se depois vocês organizarem um canal assim, dá pra escrever um importador igual fizemos pra fichas e formações.

## Pontos que ainda podem precisar de ajuste fino

- **Datas na importação de formações**: o texto de "Atualização dos arquivos de formados" não traz a data de cada formação, só o número sequencial — por isso a importação grava a data de hoje como placeholder. Se tiverem a data real em algum lugar, é só ajustar o parser (`import_parser.py`) pra pegar de lá.
- **Testar o parser da ficha** com mais exemplos reais de post do fórum antes de rodar `/ficha importar` de verdade — o formato pode variar entre posts antigos e novos.
- **Resolução de Roblox ID**: já está automática (usa a API pública do Roblox), mas ela depende do username estar escrito exatamente certo no texto/nickname — typos vão ficar sem ID resolvido e a ficha fica marcada como incompleta pra revisão.

