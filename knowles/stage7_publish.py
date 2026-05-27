"""Stage 7 — upload to YouTube via the Data API v3 (free quota).

Auth uses an OAuth user token produced once by scripts/auth_youtube.py. In CI the
token JSON lives in the YOUTUBE_TOKEN_JSON secret; locally it can be token.json.
Uploads default to PRIVATE so the human does the final trust glance before going
public (configurable via config.yaml / KNOWLES_PRIVACY / KNOWLES_PUBLISH_AT).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from . import config

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


@dataclass
class PublishResult:
    video_id: str
    url: str
    privacy: str
    thumbnail_set: bool


def _credentials() -> Credentials:
    info = config.load_json_secret("YOUTUBE_TOKEN_JSON", "token.json")
    if not info:
        raise RuntimeError(
            "No YouTube credentials. Run scripts/auth_youtube.py once, then set "
            "YOUTUBE_TOKEN_JSON (CI) or keep token.json beside the project (local)."
        )
    return Credentials.from_authorized_user_info(info, SCOPES)


def upload(video: Path, title: str, description: str, thumbnail: Path | None = None) -> PublishResult:
    creds = _credentials()
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    privacy = config.privacy_status()
    publish_at = config.publish_at()
    status: dict = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if publish_at:
        # Scheduled publish requires the video to start private.
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": config.cfg("publish", "tags", default=[]),
            "categoryId": str(config.cfg("publish", "category_id", default="27")),
        },
        "status": status,
    }

    media = MediaFileUpload(str(video), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _, response = request.next_chunk()
    video_id = response["id"]

    thumb_set = False
    if thumbnail and thumbnail.exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(str(thumbnail), mimetype="image/png")
            ).execute()
            thumb_set = True
        except Exception:
            # Custom thumbnails need a verified channel; not fatal.
            thumb_set = False

    return PublishResult(
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        privacy=status["privacyStatus"],
        thumbnail_set=thumb_set,
    )
