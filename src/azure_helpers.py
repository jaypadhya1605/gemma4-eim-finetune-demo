from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from azure.ai.ml import MLClient
from azure.identity import (
    ClientSecretCredential,
    DefaultAzureCredential,
    DeviceCodeCredential,
    InteractiveBrowserCredential,
    VisualStudioCodeCredential,
)
from azure.keyvault.secrets import SecretClient
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"


def load_project_env() -> None:
    load_dotenv(ENV_FILE, override=True)


def get_credential():
    load_project_env()
    auth_mode = os.environ.get("AZURE_AUTH_MODE", "default").lower().replace("-", "_")
    if auth_mode in {"service_principal", "client_secret"}:
        required = ["AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"]
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError(
                "AZURE_AUTH_MODE=service_principal requires these local .env values: "
                + ", ".join(missing)
            )
        return ClientSecretCredential(
            tenant_id=os.environ["AZURE_TENANT_ID"],
            client_id=os.environ["AZURE_CLIENT_ID"],
            client_secret=os.environ["AZURE_CLIENT_SECRET"],
        )
    if auth_mode == "device_code":
        return DeviceCodeCredential(tenant_id=os.environ.get("AZURE_TENANT_ID"))
    if auth_mode == "interactive_browser":
        return InteractiveBrowserCredential(tenant_id=os.environ.get("AZURE_TENANT_ID"))
    if auth_mode in {"vscode", "visual_studio_code"}:
        return VisualStudioCodeCredential(tenant_id=os.environ.get("AZURE_TENANT_ID"))
    return DefaultAzureCredential(
        exclude_interactive_browser_credential=False,
        interactive_browser_tenant_id=os.environ.get("AZURE_TENANT_ID"),
    )


def get_interactive_credential() -> InteractiveBrowserCredential:
    load_project_env()
    return InteractiveBrowserCredential(tenant_id=os.environ.get("AZURE_TENANT_ID"))


def get_mlclient() -> MLClient:
    load_project_env()
    required = ["AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP", "AZUREML_WORKSPACE_NAME"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    return MLClient(
        credential=get_credential(),
        subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
        resource_group_name=os.environ["AZURE_RESOURCE_GROUP"],
        workspace_name=os.environ["AZUREML_WORKSPACE_NAME"],
    )


def _workspace_keyvault_url(workspace: Any) -> str:
    key_vault = getattr(workspace, "key_vault", None)
    if not key_vault:
        raise RuntimeError("AzureML workspace does not expose a Key Vault reference.")
    if str(key_vault).startswith("https://"):
        return str(key_vault).rstrip("/")
    vault_name = str(key_vault).rstrip("/").split("/")[-1]
    return f"https://{vault_name}.vault.azure.net"


def get_workspace_keyvault_url(ml: MLClient | None = None) -> str:
    load_project_env()
    ml = ml or get_mlclient()
    workspace = ml.workspaces.get(os.environ["AZUREML_WORKSPACE_NAME"])
    return _workspace_keyvault_url(workspace)


def resolve_hf_token(ml: MLClient | None = None, *, required: bool = True) -> tuple[str | None, str]:
    load_project_env()
    env_token = os.environ.get("HF_TOKEN")
    if env_token:
        return env_token, "local .env / environment"

    secret_name = os.environ.get("HF_TOKEN_SECRET_NAME", "HF-TOKEN")
    try:
        ml = ml or get_mlclient()
        vault_url = get_workspace_keyvault_url(ml)
        secret = SecretClient(vault_url=vault_url, credential=get_credential()).get_secret(secret_name)
        if secret.value:
            return secret.value, f"Key Vault secret {secret_name}"
    except Exception as exc:
        if required:
            raise RuntimeError(
                f"HF_TOKEN is not set locally and Key Vault secret lookup failed for {secret_name}: {exc}"
            ) from exc
        return None, f"not found: {exc}"

    if required:
        raise RuntimeError(f"HF_TOKEN is not set locally and Key Vault secret {secret_name} is empty.")
    return None, "not found"
