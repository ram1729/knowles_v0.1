"""One-time YouTube OAuth — produces token.json for the YOUTUBE_TOKEN_JSON secret.

Works three ways:
  * As a script on a machine with a browser:   python scripts/auth_youtube.py
  * In Colab / Jupyter (no local browser):     paste this file into a cell and run,
    or just call authorize() — it auto-uses the copy-paste flow.
  * Headless / force manual flow:              python scripts/auth_youtube.py --console

Setup first (once):
  1. Google Cloud Console -> enable "YouTube Data API v3".
  2. Create an OAuth client of type "Desktop app"; download it as client_secret.json.
     - Local: put it in the project root.
     - Colab: upload it (left sidebar -> Files), it lands at /content/client_secret.json.
  3. In Colab also run:  !pip install -q google-auth-oauthlib google-api-python-client
  4. Run this. Approve with the Google account that owns the YouTube channel.
  5. token.json is written AND printed — paste that one line into the GitHub repo
     secret YOUTUBE_TOKEN_JSON.
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from google_auth_oauthlib.flow import InstalledAppFlow

# Kept in sync with knowles/stage7_publish.py (duplicated so this file is standalone).
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

# In a notebook there is no __file__; fall back to the current working directory.
try:
    ROOT = Path(__file__).resolve().parent.parent
except NameError:  # running inside a notebook cell
    ROOT = Path.cwd()

IN_NOTEBOOK = "google.colab" in sys.modules or "ipykernel" in sys.modules


def _find_client_secret() -> Path | None:
    for p in (ROOT / "client_secret.json", Path.cwd() / "client_secret.json",
              Path("/content/client_secret.json")):
        if p.exists():
            return p
    return None


def _extract_code(pasted: str) -> str:
    pasted = pasted.strip()
    if "code=" in pasted:
        # User pasted the full redirect URL (http://localhost/?...&code=XYZ&...).
        qs = parse_qs(urlparse(pasted).query)
        if qs.get("code"):
            return qs["code"][0]
    return pasted  # they pasted just the code


def authorize(client_secret: str | Path | None = None, console: bool | None = None):
    """Run the OAuth flow and return google credentials. Writes/prints token.json."""
    cs = Path(client_secret) if client_secret else _find_client_secret()
    if not cs or not cs.exists():
        raise FileNotFoundError(
            "client_secret.json not found. Create a Desktop-app OAuth client, download it, "
            "and put it in the project root (or upload to Colab /content/)."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(cs), SCOPES)
    use_console = IN_NOTEBOOK if console is None else console

    if use_console:
        # Copy-paste flow: works anywhere, no reachable localhost needed.
        flow.redirect_uri = "http://localhost"
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
        print("\n1) Open this URL and approve access:\n")
        print(auth_url)
        print("\n2) Your browser will try to load 'http://localhost/...' and show a "
              "connection error — that is expected.")
        print("3) Copy the FULL address from the browser bar (or just the code= value) "
              "and paste it below.\n")
        flow.fetch_token(code=_extract_code(input("Paste redirect URL or code: ")))
        creds = flow.credentials
    else:
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    token_json = creds.to_json()
    (ROOT / "token.json").write_text(token_json, encoding="utf-8")
    print(f"\nSaved {ROOT / 'token.json'}")
    print("\n--- Paste the line below into the GitHub secret YOUTUBE_TOKEN_JSON ---\n")
    print(token_json)
    return creds


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    console = "--console" in argv
    try:
        authorize(console=True if console else None)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
