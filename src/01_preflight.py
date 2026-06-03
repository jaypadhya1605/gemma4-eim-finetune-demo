"""
Step 01 — local and Azure readiness checks for the Gemma 4B LoRA demo.

Run:
    python src/01_preflight.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import httpx
from azure.ai.ml import MLClient
from rich import print as rprint
from rich.panel import Panel
from rich.table import Table

from azure_helpers import REPO_ROOT, get_credential, get_mlclient, load_project_env, resolve_hf_token
from demo_runtime import GEMMA_CATALOG_MODEL_ID, GEMMA_MODEL_ID

DATA_DIR = REPO_ROOT / "data"


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def check_hf_model_access(token: str) -> tuple[bool, str]:
    url = f"https://huggingface.co/{GEMMA_MODEL_ID}/resolve/main/config.json"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = httpx.get(url, headers=headers, timeout=30.0, follow_redirects=True)
    except Exception as exc:
        return False, str(exc)
    if response.status_code == 200:
        return True, "config.json reachable"
    return False, f"HTTP {response.status_code}: {response.text[:200]}"


def parse_catalog_model_uri(uri: str) -> tuple[str, str, str]:
    match = re.fullmatch(r"azureml://registries/([^/]+)/models/([^/]+)/versions/([^/]+)", uri)
    if not match:
        raise ValueError(f"Unsupported AzureML catalog model URI: {uri}")
    return match.group(1), match.group(2), match.group(3)


def check_catalog_model_access(uri: str) -> tuple[bool, str]:
    registry_name, model_name, model_version = parse_catalog_model_uri(uri)
    client = MLClient(credential=get_credential(), registry_name=registry_name)
    model = client.models.get(name=model_name, version=model_version)
    display_name = model.tags.get("displayName") if model.tags else None
    return True, f"{display_name or model.name}:{model.version} in registry {registry_name}"


def add_row(table: Table, check: str, ok: bool, detail: str) -> None:
    table.add_row(check, "OK" if ok else "BLOCKED", detail, style="green" if ok else "red")


def main() -> None:
    load_project_env()
    rprint(Panel.fit("[bold]Step 01 — Preflight checks[/bold]"))

    table = Table(title="Readiness")
    table.add_column("Check", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Detail")

    version = sys.version_info
    python_ok = (3, 10) <= (version.major, version.minor) <= (3, 12)
    add_row(table, "Python", python_ok, sys.version.split()[0])

    train_count = count_jsonl(DATA_DIR / "synthetic_train.jsonl")
    val_count = count_jsonl(DATA_DIR / "synthetic_validation.jsonl")
    add_row(table, "Synthetic data", train_count > 0 and val_count > 0, f"train={train_count}, validation={val_count}")

    try:
        ml = get_mlclient()
        workspace = ml.workspaces.get(ml.workspace_name)
        add_row(table, "AzureML workspace", True, f"{workspace.name} in {workspace.location}")
    except Exception as exc:
        rprint(table)
        rprint(f"\n[red]AzureML workspace check failed:[/red] {exc}")
        raise SystemExit(2) from exc

    try:
        compute_name = os.environ.get("AZUREML_COMPUTE_NAME", "a100-cluster-1node")
        compute = ml.compute.get(compute_name)
        size = getattr(compute, "size", None) or getattr(compute, "vm_size", "unknown")
        add_row(table, "A100 compute", "A100" in str(size), f"{compute.name}: {size}, {compute.provisioning_state}")
    except Exception as exc:
        add_row(table, "A100 compute", False, str(exc))

    model_source = os.environ.get("BASE_MODEL_SOURCE", "azureml_catalog").lower()
    if model_source in {"azureml_catalog", "catalog", "foundry"}:
        try:
            ok, detail = check_catalog_model_access(GEMMA_CATALOG_MODEL_ID)
            add_row(table, "Catalog model", ok, detail)
        except Exception as exc:
            add_row(table, "Catalog model", False, str(exc))
    else:
        try:
            hf_token, source = resolve_hf_token(ml)
            hf_ok, hf_detail = check_hf_model_access(hf_token or "")
            add_row(table, "HF token", True, source)
            add_row(table, "Gemma access", hf_ok, hf_detail)
        except Exception as exc:
            add_row(table, "HF token", False, str(exc))

    rprint(table)
    rprint("\n[bold]Next:[/bold] python src/02_prepare_data.py")


if __name__ == "__main__":
    main()
