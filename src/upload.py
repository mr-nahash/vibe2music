"""YouTube uploader: video.mp4 + metadata.json -> YouTube (Data API v3).

Setup (one time):
  1. Google Cloud project -> enable "YouTube Data API v3".
  2. OAuth consent screen -> add yourself as test user.
  3. Create OAuth client ID (Desktop app) -> download as client_secret.json
     next to this script.
  4. First run opens a browser for consent; token cached in token.json.
NOTE: until your app passes Google's API audit, API uploads are LOCKED PRIVATE.
Default here is private anyway -- you review in YouTube Studio, then publish.

Usage:
    python upload.py <set_dir> [--privacy private|unlisted|public] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
HERE = Path(__file__).parent


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
            flow = InstalledAppFlow.from_client_secrets_file(
                str(HERE / "client_secret.json"), SCOPES)
            creds = flow.run_local_server(port=0)
        token.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def upload(set_dir: Path, privacy: str = "private", dry_run: bool = False) -> str | None:
    video = set_dir / "video.mp4"
    meta = json.loads((set_dir / "metadata.json").read_text(encoding="utf-8"))
    assert video.exists(), "run render.py first"

    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": "10",  # Music
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            # AI disclosure flag -- verify current field name in API docs:
            # https://developers.google.com/youtube/v3/docs/videos#status
            "containsSyntheticMedia": True,
        },
    }
    if dry_run:
        print(json.dumps(body, indent=2))
        print(f"dry-run: would upload {video} ({video.stat().st_size/1e6:.1f} MB)")
        return None

    from googleapiclient.http import MediaFileUpload
    yt = get_service()
    req = yt.videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True),
    )
    response = None
    while response is None:
        status, response = req.next_chunk()
        if status:
            print(f"  {int(status.progress() * 100)}%", end="\r")
    vid = response["id"]
    print(f"\nuploaded: https://youtu.be/{vid} (privacy: {privacy})")
    return vid


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("set_dir", type=Path)
    p.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    try:
        upload(args.set_dir, args.privacy, args.dry_run)
    except FileNotFoundError as e:
        print(f"missing credentials file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
