# Quem É Este Leão?

Bot de quizzes visuais para redes sociais do **Sporting CP** / **#SpacesSporting**.
Todo o texto visível está em **português europeu (pt-PT)** — nunca brasileiro.

Fluxo de produção:

`SELECT PLAYER → FIND REAL PHOTOS (vários candidatos) → VALIDATE/SCORE → ANONYMIZE → CLUE → GRAPHIC → SECOND-PASS → SAVE → (X) → WAIT → REVEAL`

A fiabilidade da escolha e da anonimização da fotografia vale mais do que a velocidade.
Um falso negativo (rejeitar a imagem) é preferível a publicar um jogador reconhecível.

As fotografias **têm de ser da época em que o jogador representou o Sporting CP**
(camisola verde-e-branca / Alvalade). Fotos de outros clubes, da seleção, ou de
jogos de caridade (mesmo com o jogador visível) são rejeitadas.

## Requisitos

- Python 3.11+ (testado em 3.13)
- Linux (OpenCV headless; detector DNN **YuNet** em `assets/models/`, Haar como fallback)
- Recomendado em produção: Tesseract OCR (`tesseract-ocr`, `tesseract-ocr-por`, `tesseract-ocr-eng`) para tapar **nome** e **número de camisola** do jogador
- Opcional: credenciais da API v2 do X/Twitter

## Instalação

```bash
cd quem-e-este-leao
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
```

A base SQLite e as saídas ficam em `var/` (criada automaticamente).

## Configuração

Ver `.env.example`. Variáveis com prefixo `QEEL_`:

| Variável | Omissão | Notas |
| --- | --- | --- |
| `QEEL_DIFFICULTY` | `medium` | `easy` / `medium` / `hard` |
| `QEEL_REVEAL_DELAY` | `1h` | `30min` / `1h` / `3h` |
| `QEEL_TIMEZONE` | `Europe/Lisbon` | |
| `QEEL_DRY_RUN` | `true` | Forçado a `true` se não houver chaves X |
| `QEEL_POST_AT` | `12:00` | Hora local do post diário |
| `QEEL_WIKIMEDIA_ENABLED` | `true` | Pesquisa Commons (vários candidatos) |
| `QEEL_WIKIMEDIA_SEARCH_LIMIT` | `6` | Máximo de ficheiros Commons a descarregar |
| `QEEL_MAX_IMAGE_CANDIDATES` | `8` | Local + Wikimedia + (opcional) sintético |
| `QEEL_MIN_IMAGE_SCORE` | `35` | Abaixo disto a foto é descartada |
| `QEEL_ALLOW_SYNTHETIC` | `false` | **Produção nunca usa sintético** |
| `QEEL_OCR_ENABLED` | `true` | Tesseract se estiver instalado |
| `QEEL_ABORT_IF_RECOGNIZABLE` | `true` | Segunda passagem rejeita fugas de identidade |
| `QEEL_X_API_KEY` … | vazio | Sem isto, só pré-visualização local |

**Direitos de imagem.** A Wikimedia Commons é a fonte preferida. Fotografias
locais extra só podem ser adicionadas se o operador tiver direitos (licença
reutilizável, autorização, ou arquivo próprio) **e** se mostrarem o jogador
na época Sporting. Fonte e créditos guardam-se **internamente** (manifesto /
coluna `image_attribution`) — nunca no nome público do ficheiro. `image_kind`
é `REAL` ou `SYNTHETIC_TEST`.

## Gerar um quiz (pré-visualização)

```bash
source .venv/bin/activate
quem-e-este-leao generate --difficulty medium --reveal-in 1h --dry-run
# equivalente:
quem-e-este-leao preview --difficulty medium
# jogador concreto (slug interno):
quem-e-este-leao generate --player luis-figo --dry-run
```

Ou:

```bash
python -m quem_e_este_leao generate -d medium --dry-run
```

Saída em `examples/` (dry-run):

- `quiz_<hex>.jpg` — quadro 1080×1080, EXIF limpo, nome opaco
- `quiz_<hex>_caption.txt` — legenda pública (sem o nome)
- `quiz_<hex>_ANSWERS_NAO_PUBLICAR.txt` — **interno**, não publicar / não commitar

### Outros comandos

```bash
quem-e-este-leao publish QUIZ_ID          # rascunho → local ou X (idempotente)
quem-e-este-leao reveal QUIZ_ID
quem-e-este-leao run-once                 # gera + publica já
quem-e-este-leao reveal-due               # para cron (revelações devidas no SQLite)
quem-e-este-leao serve-scheduler          # post diário + revelações
quem-e-este-leao players
quem-e-este-leao status
quem-e-este-leao reset --yes              # reinicia o ciclo de rotação
quem-e-este-leao list-formats
```

`--quiz-id` continua a ser aceite em `publish` / `reveal`. `--reveal-in` mantém-se no `generate`.

## Pipeline de imagem

1. Recolhe **vários** candidatos (foto local curada + Wikimedia ficheiro conhecido + pesquisa Commons).
   A pesquisa **tem de** incluir Sporting CP e os `years_at_sporting` (ex.: «Luís Figo Sporting CP 1995»).
   Ficheiros Commons de outro clube/ano (ex.: Gyökeres 2018) não entram como candidato de produção.
2. Pontua: resolução, cara detectada, ocupação, **kit verde-e-branco (requisito)**, jogador dominante, crop; penaliza multi-jogador, cara minúscula, ficheiro corrupto, texto excessivo.
   Sem verde Sporting no tronco (`not_sporting_kit`) a foto é **rejeitada**. Não se publicam camisolas de outros clubes nem jogos de caridade.
3. Tenta o melhor. Se a anonimização ou a 2.ª passagem falhar, passa ao seguinte. Se nenhum for seguro, **descarta o jogador** e escolhe outro. Nunca recua para uma foto fora da época Sporting.
4. Sintético **só** com `QEEL_ALLOW_SYNTHETIC=true` (testes). Produção nunca recorre a geometria «à sorte».

### Detecção de cara

YuNet (OpenCV DNN, modelo Apache-2.0 em `assets/models/`). Haar Cascade só como fallback.
Frontal, perfil, rotações leves, acção e luz variável. Se nenhum detector for fiável: **rejeitar**.

### Anonimização

Pixelização + desfoque oval com pluma (não um rectângulo preto). Cara irreconhecível;
número de camisola e nome/apelido do jogador tapados quando a dificuldade o exige
(medium/hard), via OCR (Tesseract) e heurística compacta no peito. **Não** se
censuram publicidade, logos de patrocínio, patches de evento, datas nem nomes de
estádio — «MATCH AGAINST POVERTY» e afins podem ficar visíveis. O corpo, o
equipamento, o estádio e a acção mantêm-se. A dificuldade controla a força:

- **easy** — máscara moderada; pista mais directa
- **medium** (omissão) — máscara forte; nome/número escondidos
- **hard** — máscara extrema; pista subtil

### Segunda passagem

O detector e o OCR voltam a correr na fotografia já processada (antes da moldura).
Cara residual com alta confiança, nome/alcunha do jogador ainda legível, ou número
de camisola ainda legível → rejeitar e tentar o próximo candidato. Texto de evento,
patrocínio ou publicidade **não** rejeita. Nunca se publica só porque o
processamento não lançou uma excepção. Sem Tesseract, a segunda passagem valida
só a cara; por isso o Tesseract é recomendado em produção.

## Dificuldade (pistas)

- **easy** — nacionalidade / posição / facto simples (sem combinação única que identifique um só jogador)
- **medium** — internacional / título Sporting / academia
- **hard** — época / facto menos óbvio

As pistas são validadas contra tokens de identidade (nome, partes, alcunhas únicas).

## Rotação

Não se repete um jogador até todos os do pool actual terem saído. Depois começa
um novo ciclo. Estado em SQLite (`players_used`, `rotation_state`).

## Identidade — regras para não vazar a resposta

1. O nome do jogador **não** vai na legenda inicial, na pista, no EXIF, nem no nome do ficheiro (`quiz_<hex>.jpg`).
2. A resposta vive numa tabela `quiz_answers` **separada** (`correct_answer` / `player_name`) e num ficheiro `_ANSWERS_NAO_PUBLICAR.txt`.
3. Logs: o nome só aparece em **DEBUG**, nunca em INFO.
4. Alcunhas únicas (Pote, CR7, …) estão em `nicknames` e são bloqueadas nas pistas.
5. Não usar o nome do jogador em commits, ramos git, ou pastas públicas.

## Publicação no X

A arquitectura Tweepy mantém-se. Sem credenciais, `QEEL_DRY_RUN` fica `true` e só há pré-visualização local.

A publicação é **idempotente**: `UNIQUE(quiz_id, kind)` em `publications` + verificação de `status`.
Um retry nunca cria um segundo post. Erros de API / auth / rate-limit / media / rede são classificados e não deixam o estado inconsistente a meio (o post só é marcado depois do tweet).

Passos restantes para produção no X:

1. Criar uma app no [portal de developer do X](https://developer.x.com/) com permissão de escrita e upload de media.
2. Preencher `QEEL_X_API_KEY`, `QEEL_X_API_SECRET`, `QEEL_X_ACCESS_TOKEN`, `QEEL_X_ACCESS_TOKEN_SECRET` (e opcionalmente o bearer) no `.env`.
3. `QEEL_DRY_RUN=false`
4. Validar com `quem-e-este-leao generate --dry-run` e inspeccionar `examples/quiz_*.jpg`.
5. Publicar: `quem-e-este-leao publish QUIZ_ID --no-dry-run`
6. Revelar: `quem-e-este-leao reveal QUIZ_ID --no-dry-run` ou deixar o agendador / cron `reveal-due`.

## Agendador

Os trabalhos devidos **vivem no SQLite** (`reveal_at` + `status`, e a data do último post diário) — um restart não os perde.

```bash
# primeiro plano (systemd / docker)
quem-e-este-leao serve-scheduler
```

- Post diário à hora `QEEL_POST_AT` (omissão 12:00, fuso `Europe/Lisbon`).
- Revelações a cada 5 minutos, mais um catch-up no arranque.

### Cron (alternativa)

```cron
*/5 * * * *  cd /opt/quem-e-este-leao && .venv/bin/quem-e-este-leao reveal-due
0 12 * * *   cd /opt/quem-e-este-leao && .venv/bin/quem-e-este-leao run-once --difficulty medium --reveal-in 1h
```

O fuso da máquina deve ser Europe/Lisbon ou usar `TZ`.

## systemd

Unidade em `deploy/quem-e-este-leao.service` (agendador em primeiro plano).

```bash
sudo cp deploy/quem-e-este-leao.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now quem-e-este-leao.service
```

## Docker

```bash
cd deploy
docker compose up --build
```

O compose monta `var/` e `examples/` e corre `serve-scheduler`. Para um ciclo único:

```bash
docker compose run --rm quiz quem-e-este-leao run-once --dry-run
```

## Formatos

| id | Estado |
| --- | --- |
| `quem_e_este_leao` | **Implementado** |
| `quem_e_esta_lenda` | Esqueleto |
| `quem_marcou_este_golo` | Esqueleto |
| `de_que_epoca` | Esqueleto |
| `quem_usava_esta_camisola` | Esqueleto |
| `quem_e_este_treinador` | Esqueleto |

## Testes

```bash
source .venv/bin/activate
pytest -q
```

Cobertura: rotação, pistas sem nome / combinação única, nomes de ficheiro opacos,
EXIF limpo, força de desfoque por dificuldade, detecção YuNet, pontuação de imagens
(rejeição de camisola não-Sporting), pesquisa Commons da época Alvalade,
anonimização (fixture sintética `tests/fixtures/` em modo `SYNTHETIC_TEST`),
segunda passagem, transições SQLite, publicação idempotente (X mockado),
agendador (revelação devida + post diário), e2e dry-run com fotografia real de `assets/samples`.
Testes de OCR correm quando o Tesseract está instalado (saltam só se faltar o binário).

## Licença

MIT. As fotografias de amostra em `assets/samples/` têm licenças próprias
(CC BY / CC BY-SA / domínio público) — ver `assets/samples/ATTRIBUTION.md`.
O modelo YuNet em `assets/models/` é Apache-2.0 (OpenCV Zoo).
O emblema oficial do Sporting CP **não** é reproduzido; o branding do post é
uma barra verde `#008057` com a hashtag #SpacesSporting.
