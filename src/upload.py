"""Upload a reviewed render to YouTube, private by default."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
HERE = Path(__file__).resolve().parent


def get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    token = HERE / "token.json"
    if token.exists():
        creds = Credentials.from_authorized_user_file(str(token), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(HERE / "client_secret.json"), SCOPES)
            creds = flow.run_local_server(port=0)
        token.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def upload(set_dir: Path, privacy: str = "private", publish_at: str | None = None,
           dry_run: bool = False) -> str | None:
    video = set_dir / "video.mp4"
    metadata_path = set_dir / "metadata.json"
    if not video.exists():
        raise FileNotFoundError(f"render first: {video}")
    meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    description = str(meta.get("description", ""))
    if "ai assistance" not in description.lower():
        description += "\n\nThis music was created with AI assistance and curated by a human."
    status: dict[str, object] = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": True,
    }
    if publish_at:
        # YouTube expects an RFC 3339 timestamp and the video must stay private.
        if privacy != "private":
            raise ValueError("publish_at requires privacy=private")
        parsed = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        status["publishAt"] = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    body = {
        "snippet": {
            "title": str(meta.get("title", "Instrumental Mix"))[:100],
            "description": description,
            "tags": [str(tag) for tag in meta.get("tags", [])][:15],
            "categoryId": "10",
        },
        "status": status,
    }
    if dry_run:
        print(json.dumps(body, indent=2))
        print(f"dry-run: would upload {video} ({video.stat().st_size / 1e6:.1f} MB)")
        return None

    from googleapiclient.http import MediaFileUpload

    request = get_service().videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True),
    )
    response = None
    while response is None:
        progress, response = request.next_chunk()
        if progress:
            print(f"  {int(progress.progress() * 100)}%", end="\r")
    video_id = response["id"]
    print(f"\nuploaded: https://youtu.be/{video_id} (privacy: {privacy})")
    return video_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("set_dir", type=Path)
    parser.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    parser.add_argument("--publish-at", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        upload(args.set_dir, args.privacy, args.publish_at, args.dry_run)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
