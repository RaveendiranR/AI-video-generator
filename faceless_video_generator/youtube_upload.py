from __future__ import annotations

import argparse
import json
from pathlib import Path


def upload_video(
    video: Path,
    *,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    client_secret: Path = Path("client_secret.json"),
    token_file: Path = Path("youtube-token.json"),
    privacy: str = "private",
    publish_at: str | None = None,
    category_id: str = "22",
) -> str:
    """Upload through YouTube's official OAuth flow.

    OAuth is intentionally performed on the user's computer. No Google
    credentials are embedded in the source archive.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise RuntimeError(
            "YouTube support is optional. Install it with: "
            "python -m pip install -r requirements-youtube.txt"
        ) from exc

    if not video.is_file():
        raise FileNotFoundError(f"Video not found: {video}")
    if not client_secret.is_file():
        raise FileNotFoundError(
            f"Missing {client_secret}. Download an OAuth Desktop client JSON from Google Cloud."
        )

    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    credentials = None
    if token_file.exists():
        credentials = Credentials.from_authorized_user_file(str(token_file), scopes)
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), scopes)
            credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        token_file.write_text(credentials.to_json(), encoding="utf-8")

    if publish_at:
        privacy = "private"
    if privacy not in {"private", "unlisted", "public"}:
        raise ValueError("privacy must be private, unlisted, or public")

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": (tags or [])[:500],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at

    service = build("youtube", "v3", credentials=credentials)
    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True),
    )
    response = None
    while response is None:
        _, response = request.next_chunk()
    return f"https://www.youtube.com/watch?v={response['id']}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Upload a rendered video to YouTube.")
    parser.add_argument("video", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--client-secret", type=Path, default=Path("client_secret.json"))
    parser.add_argument("--token-file", type=Path, default=Path("youtube-token.json"))
    parser.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    parser.add_argument("--publish-at", help="RFC 3339 UTC time, for example 2026-10-01T14:00:00Z")
    args = parser.parse_args(argv)
    try:
        url = upload_video(
            args.video,
            title=args.title,
            description=args.description,
            tags=[tag.strip() for tag in args.tags.split(",") if tag.strip()],
            client_secret=args.client_secret,
            token_file=args.token_file,
            privacy=args.privacy,
            publish_at=args.publish_at,
        )
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"error: {exc}\n")
    print(url)


if __name__ == "__main__":
    main()