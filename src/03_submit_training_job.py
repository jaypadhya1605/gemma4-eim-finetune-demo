"""
src/03_submit_training_job.py
==============================
Submit the LoRA SFT training job to AzureML. The job runs training/train.py
on the A100 compute cluster, packages the small synthetic JSONL files with
the job code, and mounts the base model from the Foundry/AzureML catalog by default.

Run:
    python src/03_submit_training_job.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import base64
import zlib
from pathlib import Path

from azure.ai.ml import Input, MLClient, command
from azure.ai.ml.constants import AssetTypes, InputOutputModes
from azure.ai.ml.entities import Environment
from rich import print as rprint
from rich.panel import Panel
from rich.table import Table

from azure_helpers import get_mlclient, resolve_hf_token
from demo_runtime import GEMMA_CATALOG_MODEL_ID, GEMMA_MODEL_ID

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / ".job_state.json"
TRAINING_DIR = REPO_ROOT / "training"
DATA_DIR = REPO_ROOT / "data"
PACKAGED_DATA_DIR = TRAINING_DIR / "data"

# AzureML curated environments don't yet include Transformers 4.46 + TRL 0.11.
# We build a custom environment from training/conda.yml on top of a CUDA base image.
ENV_NAME = "gemma4-lora-sft-env"
ENV_VERSION = "6"
BASE_IMAGE = "mcr.microsoft.com/azureml/openmpi5.0-cuda12.4-ubuntu22.04:latest"


def winner_profile_enabled() -> bool:
    return os.environ.get("WINNER_TRAINING_PROFILE", "1") != "0"


def training_int(name: str, default: str) -> int:
    if winner_profile_enabled():
        return int(os.environ.get(f"WINNER_{name}", default))
    return int(os.environ.get(name, default))


def training_float(name: str, default: str) -> float:
    if winner_profile_enabled():
        return float(os.environ.get(f"WINNER_{name}", default))
    return float(os.environ.get(name, default))


def _pack_inline_file(path: Path, lines: int | None = None) -> str:
    text = path.read_text(encoding="utf-8")
    if lines is not None:
        text = "\n".join(text.splitlines()[:lines])
    return base64.b64encode(zlib.compress(text.encode("utf-8"), level=9)).decode("ascii")


def build_inline_command(cmd: str) -> str:
    """Create the remote training files inline to avoid local datastore upload."""
    if winner_profile_enabled():
        train_limit = int(os.environ.get("WINNER_INLINE_TRAIN_RECORDS", "96"))
        validation_limit = int(os.environ.get("WINNER_INLINE_VALIDATION_RECORDS", "24"))
    else:
        train_limit = int(os.environ.get("INLINE_TRAIN_RECORDS", "96"))
        validation_limit = int(os.environ.get("INLINE_VALIDATION_RECORDS", "24"))
    files = {
        "train.py": _pack_inline_file(TRAINING_DIR / "train.py"),
        "data/synthetic_train.jsonl": _pack_inline_file(DATA_DIR / "synthetic_train.jsonl", train_limit),
        "data/synthetic_validation.jsonl": _pack_inline_file(DATA_DIR / "synthetic_validation.jsonl", validation_limit),
    }
    bootstrap = (
        "python -c \"import base64,zlib,pathlib;"
        f"files={files!r};"
        "[pathlib.Path(p).parent.mkdir(parents=True, exist_ok=True) or "
        "pathlib.Path(p).write_bytes(zlib.decompress(base64.b64decode(s))) "
        "for p,s in files.items()]\""
    )
    return f"set -e; {bootstrap}; {cmd}"


def ensure_environment(ml: MLClient) -> str:
    """Create or fetch the custom training environment. Returns env reference string."""
    rprint(f"  Ensuring training environment [cyan]{ENV_NAME}:{ENV_VERSION}[/cyan]...")
    try:
        env = ml.environments.get(ENV_NAME, version=ENV_VERSION)
        rprint(f"  ✓ environment exists")
    except Exception:
        rprint("  building environment from training/conda.yml...")
        env = Environment(
            name=ENV_NAME,
            version=ENV_VERSION,
            description="Gemma 4 LoRA SFT — transformers/trl/peft on CUDA 12.4",
            image=BASE_IMAGE,
            conda_file=str(TRAINING_DIR / "conda.yml"),
        )
        env = ml.environments.create_or_update(env)
        rprint(f"  ✓ environment built")
    return f"{env.name}:{env.version}"


def stage_training_data() -> None:
    """Copy tiny JSONL files into the AzureML code package to avoid datastore streaming auth."""
    PACKAGED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("synthetic_train.jsonl", "synthetic_validation.jsonl"):
        source = DATA_DIR / name
        if not source.exists():
            raise FileNotFoundError(f"Missing training data file: {source}")
        shutil.copy2(source, PACKAGED_DATA_DIR / name)


def main() -> None:
    rprint(Panel.fit("[bold]Step 03 — Submit Gemma 4B LoRA SFT job[/bold]"))

    if not STATE_FILE.exists():
        rprint("[red].job_state.json not found. Run step 02 first.[/red]")
        sys.exit(1)
    state = json.loads(STATE_FILE.read_text())

    ml = get_mlclient()

    # 1. Ensure environment
    env_ref = ensure_environment(ml)

    inline_code = os.environ.get("AZUREML_INLINE_CODE", "1") != "0"
    if not inline_code:
        # Package the small synthetic data files with the job code. This avoids AzureML
        # datastore streaming/download auth for a dataset that is only a few KB.
        stage_training_data()

    model_source = os.environ.get("BASE_MODEL_SOURCE", "azureml_catalog").lower()
    use_catalog_model = model_source in {"azureml_catalog", "catalog", "foundry"}
    catalog_model_id = os.environ.get("AZUREML_CATALOG_MODEL_ID", GEMMA_CATALOG_MODEL_ID)

    # 3. Hyperparameters (override via env)
    model_id = os.environ.get("HF_MODEL_ID", GEMMA_MODEL_ID)
    base_model_input = (
        Input(type=AssetTypes.CUSTOM_MODEL, path=catalog_model_id, mode=InputOutputModes.RO_MOUNT)
        if use_catalog_model
        else model_id
    )

    hparams = {
        "num_epochs":           training_int("NUM_EPOCHS", "8"),
        "per_device_batch_size": training_int("PER_DEVICE_BATCH_SIZE", "2"),
        "grad_accum_steps":     training_int("GRAD_ACCUM_STEPS", "4"),
        "learning_rate":        training_float("LEARNING_RATE", "3e-4"),
        "lora_rank":            training_int("LORA_RANK", "32"),
        "lora_alpha":           training_int("LORA_ALPHA", "64"),
        "model_id":             base_model_input,
        "base_model_name":      model_id,
        "base_model_asset_id":  catalog_model_id if use_catalog_model else "",
    }

    table = Table(title="Hyperparameters")
    table.add_column("Param", style="cyan")
    table.add_column("Value")
    for k, v in hparams.items():
        table.add_row(k, str(v))
    rprint(table)

    # 4. Compose the command. Data files are packaged under ./data inside the job code.
    cmd = (
        "python train.py "
        "--model_id ${{inputs.model_id}} "
        "--base_model_name ${{inputs.base_model_name}} "
        "--base_model_asset_id ${{inputs.base_model_asset_id}} "
        "--train_file data/synthetic_train.jsonl "
        "--val_file data/synthetic_validation.jsonl "
        "--output_dir ./outputs "
        "--num_epochs ${{inputs.num_epochs}} "
        "--per_device_batch_size ${{inputs.per_device_batch_size}} "
        "--grad_accum_steps ${{inputs.grad_accum_steps}} "
        "--learning_rate ${{inputs.learning_rate}} "
        "--lora_rank ${{inputs.lora_rank}} "
        "--lora_alpha ${{inputs.lora_alpha}}"
    )

    # 5. Build the job
    environment_variables = {
        "TRANSFORMERS_NO_ADVISORY_WARNINGS": "1",
        "TOKENIZERS_PARALLELISM": "false",
    }
    if use_catalog_model:
        rprint("  Base model source: [cyan]AzureML catalog[/cyan]")
        rprint(f"  Catalog model: [cyan]{catalog_model_id}[/cyan]")
    else:
        hf_token, token_source = resolve_hf_token(ml)
        rprint(f"  HF token source: [cyan]{token_source}[/cyan]")
        environment_variables["HF_TOKEN"] = hf_token or ""

    job = command(
        code=None if inline_code else str(TRAINING_DIR),
        command=build_inline_command(cmd) if inline_code else cmd,
        environment=env_ref,
        compute=os.environ.get("AZUREML_COMPUTE_NAME", "a100-cluster-1node"),
        inputs={
            **hparams,
        },
        environment_variables=environment_variables,
        experiment_name="molina-eim-gemma4-lora-sft",
        display_name=f"gemma4-e2b-lora-r{hparams['lora_rank']}",
        description=f"LoRA SFT of {model_id} on synthetic computer-use data",
        tags={
            "workload": "molina-eim-finetune",
            "model": model_id,
            "base_model_source": "azureml_catalog" if use_catalog_model else "huggingface",
            "method": "lora-sft",
            "data_classification": "synthetic",
        },
    )

    rprint(f"\n  Submitting job to compute [cyan]{job.compute}[/cyan]...")
    submitted = ml.jobs.create_or_update(job)
    rprint(f"  ✓ job submitted: [green]{submitted.name}[/green]")
    rprint(f"  studio URL: [dim]{submitted.studio_url}[/dim]")

    # 6. Stream until terminal
    rprint("\n[bold]Streaming job status. Open the studio URL above for live logs + loss curve.[/bold]")
    ml.jobs.stream(submitted.name)
    current = ml.jobs.get(submitted.name)

    rprint(f"\n[bold]Final status: {current.status}[/bold]")
    if current.status != "Completed":
        rprint("[red]Job did not complete successfully. Check logs in studio.[/red]")
        sys.exit(2)

    state["training_job_name"] = submitted.name
    state["training_job_id"] = submitted.id
    STATE_FILE.write_text(json.dumps(state, indent=2))
    rprint(f"\n[bold green]Done.[/bold green] Next: [cyan]python src/04_register_and_deploy.py[/cyan]")


if __name__ == "__main__":
    main()
