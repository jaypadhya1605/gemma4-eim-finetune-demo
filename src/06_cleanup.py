"""
src/06_cleanup.py
==================
Tear down the managed online endpoint to stop hourly A100 billing.

By default leaves the registered LoRA adapter and the data asset in place —
they're cheap to keep and useful if you want to redeploy without retraining.

Compute cluster (defined in Bicep) is configured to auto-scale to 0 when idle,
so we don't need to delete it here.

Run:
    python src/06_cleanup.py --yes
    python src/06_cleanup.py --yes --delete-adapter
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from rich import print as rprint
from rich.panel import Panel

from azure_helpers import get_mlclient

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / ".job_state.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="Confirm cleanup")
    parser.add_argument("--delete-adapter", action="store_true",
                        help="Also delete the registered LoRA adapter model")
    args = parser.parse_args()

    if not args.yes and os.environ.get("CLEANUP_CONFIRM") != "1":
        rprint("[yellow]Cleanup is destructive. Re-run with --yes to confirm.[/yellow]")
        sys.exit(1)

    rprint(Panel.fit("[bold]Step 06 — Cleanup[/bold]"))

    if not STATE_FILE.exists():
        rprint("[yellow]No .job_state.json — nothing to clean up.[/yellow]")
        return

    state = json.loads(STATE_FILE.read_text())
    ml = get_mlclient()

    # 1. Delete online endpoint (stops A100 billing)
    endpoint_name = state.get("endpoint_name")
    if endpoint_name:
        rprint(f"  Deleting online endpoint [cyan]{endpoint_name}[/cyan]...")
        try:
            ml.online_endpoints.begin_delete(endpoint_name).result()
            rprint("  ✓ endpoint deleted")
            state.pop("endpoint_name", None)
            state.pop("deployment_name", None)
            state.pop("scoring_uri", None)
            state.pop("primary_key", None)
            state.pop("provisioning_state", None)
            state.pop("endpoint_variants", None)
        except Exception as e:
            rprint(f"[red]  Delete failed: {e}[/red]")
    else:
        rprint("[dim]  No endpoint in state — skipping.[/dim]")

    # 2. Optionally delete the adapter model
    if args.delete_adapter:
        adapter = state.get("adapter_model")
        if adapter:
            name, version = adapter.split(":")
            rprint(f"  Deleting adapter model [cyan]{name}:{version}[/cyan]...")
            try:
                ml.models.delete(name, version=version)
                rprint("  ✓ adapter deleted")
                state.pop("adapter_model", None)
            except Exception as e:
                rprint(f"[red]  Delete failed: {e}[/red]")
        else:
            rprint("[dim]  No adapter in state — skipping.[/dim]")

    STATE_FILE.write_text(json.dumps(state, indent=2))
    rprint("\n[bold green]Cleanup complete. A100 hourly billing has stopped.[/bold green]")
    rprint("[dim]Compute cluster auto-scales to 0 when idle — no action needed.[/dim]")


if __name__ == "__main__":
    main()
