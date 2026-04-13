"""One-shot: set repo variables + secrets via GitHub REST API."""
import base64
import json
import sys
import urllib.request
from pathlib import Path
from nacl import encoding, public

REPO = "Madeira-Friends-Enterprise/scrapper-threehouse-barcelo"
PAT = sys.argv[1]
API = "https://api.github.com"

HEADERS = {
    "Authorization": f"Bearer {PAT}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "Content-Type": "application/json",
}


def req(method, path, body=None):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, method=method, headers=HEADERS, data=data)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def encrypt_secret(pubkey_b64: str, value: str) -> str:
    pk = public.PublicKey(pubkey_b64.encode(), encoding.Base64Encoder())
    box = public.SealedBox(pk)
    return base64.b64encode(box.encrypt(value.encode())).decode()


def set_variable(name, value):
    status, _ = req("POST", f"/repos/{REPO}/actions/variables", {"name": name, "value": value})
    if status == 409:
        req("PATCH", f"/repos/{REPO}/actions/variables/{name}", {"name": name, "value": value})
        print(f"  variable {name} updated")
    elif status in (201, 204):
        print(f"  variable {name} created")
    else:
        print(f"  variable {name} FAILED status={status}")


def set_secret(name, value, pubkey_b64, key_id):
    encrypted = encrypt_secret(pubkey_b64, value)
    status, _ = req(
        "PUT",
        f"/repos/{REPO}/actions/secrets/{name}",
        {"encrypted_value": encrypted, "key_id": key_id},
    )
    if status in (201, 204):
        print(f"  secret {name} set")
    else:
        print(f"  secret {name} FAILED status={status}")


print("fetching public key...")
status, pk = req("GET", f"/repos/{REPO}/actions/secrets/public-key")
if status != 200:
    print(f"FAIL status={status} body={pk}")
    sys.exit(1)

print("setting variables...")
set_variable("GOOGLE_SHEET_ID", "1HPyd0LnqI7c1eKKY4gGQcQ__ct0hnVZxkUaOeEYAJKY")
set_variable("GOOGLE_SHEET_GID", "1379799510")

print("setting secrets...")
sa_json = Path("credentials/service_account.json").read_text(encoding="utf-8")
set_secret("GOOGLE_SERVICE_ACCOUNT_JSON", sa_json, pk["key"], pk["key_id"])
set_secret(
    "OPENROUTER_API_KEY",
    "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",
    pk["key"],
    pk["key_id"],
)
print("done.")
