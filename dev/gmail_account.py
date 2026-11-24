"""Create the Gmail mail account in the dev Paperless (http://localhost:8011) from an env file.

    uv run dev/gmail_account.py PATH/TO/gmail.env

The file holds GMAIL_ADDRESS and GMAIL_APP_PASSWORD (a Google app password).
Nothing secret is printed. Existing account with the same name: password updated.
"""

from __future__ import annotations

import base64
import json
import sys
import urllib.request
from pathlib import Path

API = "http://localhost:8011/api/mail_accounts/"
NAME = "GMail"
AUTH = "Basic " + base64.b64encode(b"admin:admin").decode()


def call(method: str, url: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(url, method=method, headers={"Authorization": AUTH, "Content-Type": "application/json"})
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data) as resp:
        return json.loads(resp.read() or b"{}")


def main() -> None:
    env = {}
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    address, password = env.get("GMAIL_ADDRESS"), env.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not address or not password:
        sys.exit("GMAIL_ADDRESS or GMAIL_APP_PASSWORD missing")
    account = {
        "name": NAME,
        "imap_server": "imap.gmail.com",
        "imap_port": 993,
        "imap_security": 2,  # SSL
        "username": address,
        "password": password,
    }
    existing = [a for a in call("GET", API)["results"] if a["name"] == NAME]
    if existing:
        call("PATCH", f"{API}{existing[0]['id']}/", account)
        print(f"updated mail account #{existing[0]['id']} {NAME}")
    else:
        created = call("POST", API, account)
        print(f"created mail account #{created['id']} {NAME}")


if __name__ == "__main__":
    main()
