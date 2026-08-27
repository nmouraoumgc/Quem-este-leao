# Quem É Este Leão?

Bot de quizzes visuais para redes sociais do **Sporting CP** / **#SpacesSporting**.
Todo o texto visível está em **português europeu (pt-PT)** — nunca brasileiro.

Fluxo: escolhe um jogador da base → obtém uma fotografia reutilizável →
desfoca **só a cara** (e nome/número quando visíveis) → gera uma pista fácil
sem identificar o jogador → publica o post. A revelação sai depois de 30 min,
1 hora (omissão) ou 3 horas.

## Requisitos

- Python 3.11+ (testado em 3.13)
- Linux (OpenCV headless; Haar cascade incluído no `opencv-python-headless`)
- Opcional: Tesseract OCR (`tesseract-ocr`) para censurar números/nomes no equipamento
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
| `QEEL_WIKIMEDIA_ENABLED` | `true` | Pesquisa Commons (licenças reutilizáveis) |
| `QEEL_X_API_KEY` … | vazio | Sem isto, só pré-visualização local |

**Direitos de imagem.** A Wikimedia Commons é a fonte preferida. Fotografias
locais extra só podem ser adicionadas se o operador tiver direitos (licença
reutilizável, autorização, ou arquivo próprio). Fonte e créditos guardam-se
**internamente** (manifesto / coluna `image_attribution`) — nunca no nome
público do ficheiro.

## Gerar um quiz (pré-visualização)

```bash
source .venv/bin/activate
quem-e-este-leao generate --difficulty medium --reveal-in 1h
```

Ou:

```bash
python -m quem_e_este_leao generate -d medium
```

Saída em `examples/` (dry-run):

- `quiz_<hex>.jpg` — quadro 1080×1080, EXIF limpo, nome opaco
- `quiz_<hex>_caption.txt` — legenda pública (sem o nome)
- `quiz_<hex>_ANSWERS_NAO_PUBLICAR.txt` — **interno**, não publicar

### Outros comandos

```bash
quem-e-este-leao publish --quiz-id …        # rascunho → local ou X
quem-e-este-leao reveal --quiz-id …
quem-e-este-leao run-once                   # gera + publica já
quem-e-este-leao reveal-due                 # para cron
quem-e-este-leao serve-scheduler            # APScheduler em primeiro plano
quem-e-este-leao list-formats
```

## Dificuldade

- **easy** — desfoque moderado da cara; pista mais directa; mais contexto visível
- **medium** (omissão) — desfoque forte; nome e número escondidos; pista menos óbvia
- **hard** — anonimização muito forte; cara, nome, número e outros detalhes; pista subtil

Se, em medium/hard, o processamento não conseguir esconder a cara, o candidato
é **abortado** e tenta-se outra fotografia/jogador — nunca se publica uma imagem reconhecível.

## Rotação

Não se repete um jogador até todos os do pool actual terem saído. Depois começa
um novo ciclo. Estado em SQLite (`players_used`, `rotation_state`).

## Identidade — regras para não vazar a resposta

1. O nome do jogador **não** vai na legenda inicial, na pista, no EXIF, nem no nome do ficheiro (`quiz_<hex>.jpg`).
2. A resposta vive numa tabela `quiz_answers` **separada** e num ficheiro `_ANSWERS_NAO_PUBLICAR.txt`.
3. Logs: o nome só aparece em **DEBUG**, nunca em INFO.
4. Alcunhas únicas (Pote, CR7, …) estão em `nicknames` e são bloqueadas nas pistas.
5. Não usar o nome do jogador em commits, ramos git, ou pastas públicas.

## Cron

```cron
# a cada 5 minutos — fuso da máquina deve ser Europe/Lisbon ou usar TZ
*/5 * * * *  cd /opt/quem-e-este-leao && .venv/bin/quem-e-este-leao reveal-due
```

Um ciclo diário de publicação:

```cron
0 18 * * *  cd /opt/quem-e-este-leao && .venv/bin/quem-e-este-leao run-once --difficulty medium --reveal-in 1h
```

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

Os esqueletos existem para extensão futura (arquivo de golos, treinadores, camisolas históricas).

## Testes

```bash
source .venv/bin/activate
pytest
```

Cobertura mínima: rotação, pistas sem nome, nomes de ficheiro opacos, EXIF limpo,
força de desfoque por dificuldade, revelação devida.

## Licença

MIT. As fotografias de amostra em `assets/samples/` têm licenças próprias
(CC BY / CC BY-SA / domínio público) — ver `assets/samples/ATTRIBUTION.md`.
O emblema oficial do Sporting CP **não** é reproduzido; o branding do post é
uma barra verde `#008057` com a hashtag #SpacesSporting.
