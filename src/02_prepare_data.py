"""
src/02_prepare_data.py
=======================
Upload data/synthetic_*.jsonl as an AzureML Data asset (URI_FOLDER type).
The training job mounts this asset and reads the JSONL files directly.

Run:
    python src/02_prepare_data.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from azure.ai.ml.constants import AssetTypes
from azure.ai.ml.entities import Data
from rich import print as rprint
from rich.panel import Panel

from azure_helpers import get_mlclient

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
STATE_FILE = REPO_ROOT / ".job_state.json"

DATA_ASSET_NAME = "gemma4-eim-synthetic"
DATA_ASSET_VERSION = "1"


def main() -> None:
    rprint(Panel.fit("[bold]Step 02 — Upload synthetic data to AzureML[/bold]"))

    train = DATA_DIR / "synthetic_train.jsonl"
    val = DATA_DIR / "synthetic_validation.jsonl"
    if not train.exists() or not val.exists():
        rprint("[red]Missing JSONL files. Run: python data/generate_synthetic_data.py[/red]")
        sys.exit(1)

    rprint(f"  train: {train} ({train.stat().st_size:,} bytes)")
    rprint(f"  val:   {val} ({val.stat().st_size:,} bytes)")

    ml = get_mlclient()

    asset = Data(
        name=DATA_ASSET_NAME,
        version=DATA_ASSET_VERSION,
        description="Synthetic computer-use / extraction training data for Gemma 4B LoRA SFT. "
                    "Deterministic, fake IDs only, no Molina data.",
        path=str(DATA_DIR),
        type=AssetTypes.URI_FOLDER,
        tags={
            "workload": "molina-eim-finetune",
            "model_target": "gemma-4-E4B-it",
            "data_classification": "synthetic",
        },
    )

    rprint(f"\n  Registering asset [cyan]{DATA_ASSET_NAME}:{DATA_ASSET_VERSION}[/cyan]...")
    try:
        registered = ml.data.create_or_update(asset)
    except Exception as e:
        if "already exists" in str(e).lower():
            rprint("[yellow]Version already exists. Fetching existing.[/yellow]")
            registered = ml.data.get(DATA_ASSET_NAME, version=DATA_ASSET_VERSION)
        else:
            raise

    rprint(f"  ✓ registered: [green]{registered.name}:{registered.version}[/green]")
    rprint(f"  path: [dim]{registered.path}[/dim]")

    state = {
        "data_asset_name": DATA_ASSET_NAME,
        "data_asset_version": DATA_ASSET_VERSION,
        "data_asset_id": registered.id,
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))
    rprint(f"\n[bold green]State saved.[/bold green] Next: [cyan]python src/03_submit_training_job.py[/cyan]")


if __name__ == "__main__":
    main()
