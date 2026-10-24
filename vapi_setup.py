"""Point your Vapi number at CheckIn for INBOUND calls (run after PUBLIC_URL is set; re-run if it changes).

  python vapi_setup.py          # configure the number
  python vapi_setup.py --show   # print the number's current config (no changes)

Sets the number's server to PUBLIC_URL/vapi/end (with our secret in X-Vapi-Secret) and clears assistantId,
so Vapi sends an `assistant-request` for every incoming call and we answer with a fresh assistant.
Request format: https://docs.vapi.ai/api-reference/phone-numbers/update
"""
import json
import sys

import requests

from checkin import config

URL = "https://api.vapi.ai/phone-number/{}"


def main() -> None:
    need = {"VAPI_API_KEY": config.VAPI_API_KEY, "VAPI_PHONE_NUMBER_ID": config.VAPI_PHONE_NUMBER_ID,
            "PUBLIC_URL": config.PUBLIC_URL, "VAPI_SECRET": config.VAPI_SECRET}
    if missing := [k for k, v in need.items() if not v]:
        sys.exit(f"Missing in .env: {', '.join(missing)}")
    url, auth = URL.format(config.VAPI_PHONE_NUMBER_ID), {"Authorization": f"Bearer {config.VAPI_API_KEY}"}
    if "--show" in sys.argv:
        r = requests.get(url, headers=auth, timeout=30)
    else:
        body = {"assistantId": None, "server": {"url": f"{config.PUBLIC_URL}/vapi/end",
                                                "headers": {"X-Vapi-Secret": config.VAPI_SECRET}}}
        r = requests.patch(url, json=body, headers=auth, timeout=30)
    if not r.ok:
        sys.exit(f"Vapi error {r.status_code}: {r.text[:600]}")
    d = r.json()
    if isinstance(d.get("server"), dict):  # never print the secret
        d["server"] = {**d["server"], "headers": "<hidden>" if d["server"].get("headers") else None}
    print(json.dumps({k: d.get(k) for k in ("id", "provider", "name", "number", "assistantId", "server")}, indent=2))


if __name__ == "__main__":
    main()
