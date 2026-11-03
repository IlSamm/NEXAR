"""Genera credenziali locali una sola volta, senza scriverle nei file distribuiti."""
import json
import secrets
from core import ASSET_ROOT as ASSETS, CONFIG_FILE as private
if private.exists():
    print("config.json esiste già, nessuna modifica ai tuoi segreti.")
else:
    template = json.loads((ASSETS / "config.example.json").read_text(encoding="utf-8"))
    template["access_token"] = secrets.token_urlsafe(32)
    private.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    print("config.json creato. Aprilo: troverai access_token per la dashboard.")
