"""Launch the complete local vibe2music web application."""
from __future__ import annotations

import os
import threading
import webbrowser

from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    if not os.environ.get("ATLASCLOUD_API_KEY", "").strip():
        raise SystemExit(
            "Missing ATLASCLOUD_API_KEY.\n"
            "Copy .env.example to .env, paste your Atlas Cloud key, then run again."
        )
    os.environ["API_TOKEN"] = "vibe2music-local"
    os.environ["V2M_ENGINE"] = "atlas"

    import uvicorn

    threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:8000")).start()
    uvicorn.run("src.server:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
