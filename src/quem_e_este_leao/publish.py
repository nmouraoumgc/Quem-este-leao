"""Publicadores: pré-visualização local e X (Twitter) via API v2."""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from quem_e_este_leao import db
from quem_e_este_leao.config import Settings
from quem_e_este_leao.logging_setup import get_logger, log_answer

log = get_logger("publish")

ANSWERS_BANNER = """\
############################################################
#  NÃO PUBLICAR — FICHEIRO INTERNO COM A RESPOSTA
#  Não anexar a posts, stories, nem ao repositório público
#  se a pasta examples/ for partilhada sem revisão.
############################################################
"""


class PublishError(RuntimeError):
    """Falha de rede / API / autenticação ao publicar."""


class Publisher(ABC):
    channel: str

    @abstractmethod
    def publish_quiz(self, quiz_id: str) -> str | None:
        """Publica o post do quiz. Devolve um id remoto, se existir."""

    @abstractmethod
    def publish_reveal(self, quiz_id: str) -> str | None:
        """Publica a revelação."""


def _existing_remote(conn, quiz_id: str, kind: str) -> str | None:
    pub = db.get_publication(conn, quiz_id, kind)
    if pub is not None and pub["remote_id"]:
        return str(pub["remote_id"])
    row = db.get_quiz(conn, quiz_id)
    if row is None:
        return None
    keys = row.keys()
    if kind == "quiz" and "x_quiz_post_id" in keys and row["x_quiz_post_id"]:
        return str(row["x_quiz_post_id"])
    if kind == "reveal" and "x_reveal_post_id" in keys and row["x_reveal_post_id"]:
        return str(row["x_reveal_post_id"])
    return None


class LocalPreviewPublisher(Publisher):
    channel = "local"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.preview_dir = settings.preview_dir
        self.preview_dir.mkdir(parents=True, exist_ok=True)

    def _copy_image(self, src: Path, quiz_id: str) -> Path:
        dest = self.preview_dir / src.name
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        return dest

    def publish_quiz(self, quiz_id: str) -> str | None:
        tz = ZoneInfo(self.settings.timezone)
        now = datetime.now(tz)
        with db.session(self.settings.database_path) as conn:
            row = db.get_quiz(conn, quiz_id)
            if row is None:
                raise KeyError(f"Quiz inexistente: {quiz_id}")
            existing = _existing_remote(conn, quiz_id, "quiz")
            if row["status"] in (db.STATUS_PUBLISHED, db.STATUS_REVEALED) and existing:
                log.info("Quiz %s já publicado localmente — idempotente.", quiz_id)
                return existing
            src = Path(row["processed_image_path"])
            dest = self._copy_image(src, quiz_id)
            caption_path = self.preview_dir / f"{src.stem}_caption.txt"
            caption_path.write_text(row["caption"] + "\n", encoding="utf-8")
            answer_row = db.get_answer(conn, quiz_id)
            answers_path = self.preview_dir / f"{src.stem}_ANSWERS_NAO_PUBLICAR.txt"
            answer_name = answer_row["correct_answer"] if answer_row else "(desconhecida)"
            fact = (answer_row["interesting_fact"] if answer_row else None) or ""
            answers_path.write_text(
                ANSWERS_BANNER
                + f"\nquiz_id: {quiz_id}\n"
                + f"ficheiro_imagem: {dest.name}\n"
                + f"resposta: {answer_name}\n"
                + f"pista (já pública): {row['clue']}\n"
                + f"facto: {fact}\n"
                + f"dificuldade: {row['difficulty']}\n"
                + "\nEste ficheiro NÃO deve ser publicado.\n",
                encoding="utf-8",
            )
            reveal_dt = now + timedelta(seconds=self.settings.reveal_delay_seconds)
            if row["reveal_dt"]:
                reveal_dt_iso = row["reveal_dt"]
            else:
                reveal_dt_iso = reveal_dt.isoformat()
            db.mark_published(
                conn,
                quiz_id,
                publication_dt=now.isoformat(),
                reveal_dt=reveal_dt_iso,
                channel=self.channel,
                remote_id=str(dest),
            )
            log.info("Pré-visualização local gravada em %s", dest)
            log_answer("Resposta escrita em ficheiro interno (não publicar): %s", answer_name)
            return str(dest)

    def publish_reveal(self, quiz_id: str) -> str | None:
        with db.session(self.settings.database_path) as conn:
            row = db.get_quiz(conn, quiz_id)
            if row is None:
                raise KeyError(f"Quiz inexistente: {quiz_id}")
            existing = _existing_remote(conn, quiz_id, "reveal")
            if row["status"] == db.STATUS_REVEALED and existing:
                log.info("Revelação %s já publicada localmente — idempotente.", quiz_id)
                return existing
            src = Path(row["processed_image_path"])
            reveal_path = self.preview_dir / f"{src.stem}_reveal.txt"
            reveal_path.write_text(row["reveal_caption"] + "\n", encoding="utf-8")
            db.mark_revealed(conn, quiz_id, channel=self.channel, remote_id=str(reveal_path))
            log.info("Revelação local gravada em %s", reveal_path.name)
            return str(reveal_path)


class XPublisher(Publisher):
    channel = "x"

    def __init__(self, settings: Settings, *, client=None, api_v1=None) -> None:
        self.settings = settings
        self._client_override = client
        self._api_v1_override = api_v1
        if client is None and api_v1 is None and not settings.has_x_credentials:
            raise RuntimeError(
                "Credenciais X em falta — a usar LocalPreviewPublisher. "
                "Definir QEEL_X_API_KEY / SECRET / ACCESS_TOKEN / ACCESS_TOKEN_SECRET."
            )

    def _client(self):  # type: ignore[no-untyped-def]
        if self._client_override is not None:
            return self._client_override
        import tweepy

        return tweepy.Client(
            bearer_token=self.settings.x_bearer_token or None,
            consumer_key=self.settings.x_api_key,
            consumer_secret=self.settings.x_api_secret,
            access_token=self.settings.x_access_token,
            access_token_secret=self.settings.x_access_token_secret,
        )

    def _api_v1(self):  # type: ignore[no-untyped-def]
        if self._api_v1_override is not None:
            return self._api_v1_override
        import tweepy

        auth = tweepy.OAuth1UserHandler(
            self.settings.x_api_key,
            self.settings.x_api_secret,
            self.settings.x_access_token,
            self.settings.x_access_token_secret,
        )
        return tweepy.API(auth)

    def _classify_error(self, exc: BaseException) -> str:
        name = type(exc).__name__
        msg = str(exc).lower()
        if "401" in msg or "unauthorized" in msg or "auth" in name.lower():
            return "auth"
        if "429" in msg or "rate" in msg or "too many" in msg:
            return "rate_limit"
        if "media" in msg:
            return "media"
        if "timeout" in msg or "connection" in msg or "network" in msg:
            return "network"
        return "api"

    def publish_quiz(self, quiz_id: str) -> str | None:
        with db.session(self.settings.database_path) as conn:
            row = db.get_quiz(conn, quiz_id)
            if row is None:
                raise KeyError(f"Quiz inexistente: {quiz_id}")
            existing = _existing_remote(conn, quiz_id, "quiz")
            if row["status"] in (db.STATUS_PUBLISHED, db.STATUS_REVEALED) and existing:
                log.info("Quiz %s já no X — retry sem novo post.", quiz_id)
                return existing
            image_path = row["processed_image_path"]
            caption = row["caption"]
            reveal_dt_existing = row["reveal_dt"]

        try:
            media = self._api_v1().media_upload(image_path)
            tweet = self._client().create_tweet(
                text=caption,
                media_ids=[media.media_id],
            )
            remote_id = str(tweet.data["id"])
        except Exception as exc:  # noqa: BLE001
            kind = self._classify_error(exc)
            log.error("Falha a publicar quiz no X (%s): %s", kind, type(exc).__name__)
            raise PublishError(f"X {kind}: {type(exc).__name__}") from exc

        tz = ZoneInfo(self.settings.timezone)
        now = datetime.now(tz)
        reveal_dt = now + timedelta(seconds=self.settings.reveal_delay_seconds)
        with db.session(self.settings.database_path) as conn:
            db.mark_published(
                conn,
                quiz_id,
                publication_dt=now.isoformat(),
                reveal_dt=reveal_dt_existing or reveal_dt.isoformat(),
                channel=self.channel,
                remote_id=remote_id,
            )
        log.info("Quiz publicado no X (id remoto omitido no INFO).")
        return remote_id

    def publish_reveal(self, quiz_id: str) -> str | None:
        with db.session(self.settings.database_path) as conn:
            row = db.get_quiz(conn, quiz_id)
            if row is None:
                raise KeyError(f"Quiz inexistente: {quiz_id}")
            existing = _existing_remote(conn, quiz_id, "reveal")
            if row["status"] == db.STATUS_REVEALED and existing:
                log.info("Revelação %s já no X — retry sem novo post.", quiz_id)
                return existing
            text = row["reveal_caption"]

        try:
            tweet = self._client().create_tweet(text=text)
            remote_id = str(tweet.data["id"])
        except Exception as exc:  # noqa: BLE001
            kind = self._classify_error(exc)
            log.error("Falha a revelar no X (%s): %s", kind, type(exc).__name__)
            raise PublishError(f"X {kind}: {type(exc).__name__}") from exc

        with db.session(self.settings.database_path) as conn:
            db.mark_revealed(conn, quiz_id, channel=self.channel, remote_id=remote_id)
        log.info("Revelação publicada no X.")
        return remote_id


def get_publisher(settings: Settings) -> Publisher:
    if settings.dry_run or not settings.has_x_credentials:
        return LocalPreviewPublisher(settings)
    return XPublisher(settings)
