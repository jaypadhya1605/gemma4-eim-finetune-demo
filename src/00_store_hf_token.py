"""
Step 00 — securely store the Hugging Face token in the AzureML workspace Key Vault.

Run this from a local terminal. The token is read with getpass, so it is not
echoed to the screen and should not be pasted into chat.

Run:
    python src/00_store_hf_token.py
"""
from __future__ import annotations

import getpass
import os

from azure.keyvault.secrets import SecretClient
from rich import print as rprint
from rich.panel import Panel

from azure_helpers import get_credential, get_mlclient, get_workspace_keyvault_url, load_project_env


def main() -> None:
    load_project_env()
    rprint(Panel.fit("[bold]Step 00 — Store HF token in Key Vault[/bold]"))

    ml = get_mlclient()
    vault_url = get_workspace_keyvault_url(ml)
    secret_name = os.environ.get("HF_TOKEN_SECRET_NAME", "HF-TOKEN")

    token = getpass.getpass("Paste Hugging Face read token: ").strip()
    if not token:
        raise SystemExit("No token entered; nothing was stored.")

    client = SecretClient(vault_url=vault_url, credential=get_credential())
    client.set_secret(secret_name, token)
    rprint(f"[green]Stored token as Key Vault secret {secret_name} in {vault_url}.[/green]")


if __name__ == "__main__":
    main()
