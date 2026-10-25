#!/usr/bin/env python3
"""Fetch QORIX website-channel products for the catalogue builders.

Two paths, same output shape ({"http": status, "body": {...}}):

- Local (Eva) runs: no QORIX_API_KEY in the environment, so the
  vault-backed qorix.py CLI is used, exactly as before. The key is
  never read here and never written anywhere.
- GitHub Action runs: QORIX_API_KEY is set from a repo secret, so the
  public reseller API is called directly with a Bearer header and a
  browser User-Agent (Cloudflare 403s non-browser agents, error 1010).

If neither path is available (no key and no CLI on disk), fail loudly
instead of returning an empty catalogue — a failed build must never
publish.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://qorixlab.com/api/public/reseller/v1"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def fetch_products():
    key = os.environ.get("QORIX_API_KEY")
    if key:
        req = urllib.request.Request(
            BASE_URL + "/products?channel=" + urllib.parse.quote("website"),
            method="GET")
        req.add_header("Authorization", "Bearer " + key)
        req.add_header("User-Agent", UA)
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                return {"http": resp.status,
                        "body": json.loads(resp.read().decode())}
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode())
            except Exception:
                body = {"raw": "unreadable"}
            return {"http": e.code, "body": body}
    base = Path(__file__).resolve().parent
    cli = (base.parent / "custom-connectors" / "custom.legacy-qorix"
           / "bin" / "qorix.py")
    if not cli.exists():
        raise SystemExit("QORIX_API_KEY is not set and the qorix.py CLI "
                         "is not available here — refusing to build.")
    import subprocess
    import sys
    res = subprocess.run([sys.executable, str(cli), "products", "website"],
                         capture_output=True, text=True, timeout=60)
    return json.loads(res.stdout)
