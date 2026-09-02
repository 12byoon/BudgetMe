"""Standalone probe for the Teller API using mTLS client certificates.

This is NOT part of the Flask app. It calls Teller's REST API directly, which
requires a Teller application with client certificates (development or
production, not sandbox). Configure via environment variables / .env:

    TELLER_ACCESS_TOKEN   access token from a completed Teller Connect enrollment
    TELLER_CERT_FILE      path to your Teller client certificate (.pem)
    TELLER_KEY_FILE       path to your Teller private key (.pem)

Usage:  python teller.py
"""
import os
import sys

import requests
from dotenv import load_dotenv


def main():
    load_dotenv()

    access_token = os.getenv("TELLER_ACCESS_TOKEN")
    cert_file = os.getenv("TELLER_CERT_FILE")
    key_file = os.getenv("TELLER_KEY_FILE")

    missing = [
        name
        for name, value in (
            ("TELLER_ACCESS_TOKEN", access_token),
            ("TELLER_CERT_FILE", cert_file),
            ("TELLER_KEY_FILE", key_file),
        )
        if not value
    ]
    if missing:
        print("Missing environment variables: " + ", ".join(missing))
        return 1

    resp = requests.get(
        "https://api.teller.io/accounts",
        auth=(access_token, ""),
        cert=(cert_file, key_file),
        timeout=30,
    )
    if resp.ok:
        print(resp.json())
        return 0
    print(f"Error: {resp.status_code}, {resp.text}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
