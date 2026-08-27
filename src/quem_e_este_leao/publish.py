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


class Publisher(ABC):
    channel: str

    @abstractmethod
    def publish_quiz(self, quiz_id: str) -> str | None:
        """Publica o post do quiz. Devolve um id remoto, se existir."""

    @abstractmethod
    def publish_reveal(self, quiz_id: str) -> str | None:
        """Publica a revelação."""


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
            src = Path(row["processed_image_path"])
            reveal_path = self.preview_dir / f"{src.stem}_reveal.txt"
            reveal_path.write_text(row["reveal_caption"] + "\n", encoding="utf-8")
            db.mark_revealed(conn, quiz_id, channel=self.channel, remote_id=str(reveal_path))
            log.info("Revelação local gravada em %s", reveal_path.name)
            return str(reveal_path)


class XPublisher(Publisher):
    channel = "x"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if not settings.has_x_credentials:
            raise RuntimeError(
                "Credenciais X em falta — a usar LocalPreviewPublisher. "
                "Definir QEEL_X_API_KEY / SECRET / ACCESS_TOKEN / ACCESS_TOKEN_SECRET."
            )

    def _client(self):  # type: ignore[no-untyped-def]
        import tweepy

        return tweepy.Client(
            bearer_token=self.settings.x_bearer_token or None,
            consumer_key=self.settings.x_api_key,
            consumer_secret=self.settings.x_api_secret,
            access_token=self.settings.x_access_token,
            access_token_secret=self.settings.x_access_token_secret,
        )

    def _api_v1(self):  # type: ignore[no-untyped-def]
        import tweepy

        auth = tweepy.OAuth1UserHandler(
            self.settings.x_api_key,
            self.settings.x_api_secret,
            self.settings.x_access_token,
            self.settings.x_access_token_secret,
        )
        return tweepy.API(auth)

    def publish_quiz(self, quiz_id: str) -> str | None:
        with db.session(self.settings.database_path) as conn:
            row = db.get_quiz(conn, quiz_id)
            if row is None:
                raise KeyError(f"Quiz inexistente: {quiz_id}")
            media = self._api_v1().media_upload(row["processed_image_path"])
            tweet = self._client().create_tweet(
                text=row["caption"],
                media_ids=[media.media_id],
            )
            remote_id = str(tweet.data["id"])
            tz = ZoneInfo(self.settings.timezone)
            now = datetime.now(tz)
            reveal_dt = now + timedelta(seconds=self.settings.reveal_delay_seconds)
            db.mark_published(
                conn,
                quiz_id,
                publication_dt=now.isoformat(),
                reveal_dt=row["reveal_dt"] or reveal_dt.isoformat(),
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
            tweet = self._client().create_tweet(text=row["reveal_caption"])
            remote_id = str(tweet.data["id"])
            db.mark_revealed(conn, quiz_id, channel=self.channel, remote_id=remote_id)
            log.info("Revelação publicada no X.")
            return remote_id


def get_publisher(settings: Settings) -> Publisher:
    if settings.dry_run or not settings.has_x_credentials:
        return LocalPreviewPublisher(settings)
    return XPublisher(settings)
