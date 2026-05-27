"""One-time local YouTube OAuth. Run on your own machine (needs a browser).

    1. In Google Cloud Console, enable "YouTube Data API v3".
    2. Create an OAuth client of type "Desktop app", download it as client_secret.json
       into the project root.
    3. python scripts/auth_youtube.py
    4. A browser opens; approve with the Google account that owns the channel.
    5. token.json is written. Paste its one-line contents into the GitHub repo
       secret YOUTUBE_TOKEN_JSON (printed at the end for convenience).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from knowles.stage7_publish import SCOPES  # noqa: E402


def main() -> int:
    client_secret = ROOT / "client_secret.json"
    if not client_secret.exists():
        print("ERROR: client_secret.json not found in project root. See the docstring.")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    token_path = ROOT / "token.json"
    token_json = creds.to_json()
    token_path.write_text(token_json, encoding="utf-8")

    print(f"\nSaved {token_path}")
    print("\n--- Paste the line below into the GitHub secret YOUTUBE_TOKEN_JSON ---\n")
    print(token_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
