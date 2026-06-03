"""Deploy the Foundry/AzureML catalog Gemma model to an A100 online endpoint."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from azure.ai.ml import MLClient
from azure.ai.ml.entities import (
    CodeConfiguration,
    Environment,
    ManagedOnlineDeployment,
    ManagedOnlineEndpoint,
    OnlineRequestSettings,
    ProbeSettings,
)
from azure.core.exceptions import ResourceExistsError
from rich import print as rprint
from rich.panel import Panel

from azure_helpers import get_mlclient, load_project_env
from demo_runtime import DEFAULT_DEPLOYMENT_NAME, DEFAULT_ENDPOINT_NAME, GEMMA_CATALOG_MODEL_ID, GEMMA_MODEL_ID

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / ".job_state.json"

ENDPOINT_INSTANCE_SKU = "Standard_NC24ads_A100_v4"
INFER_ENV_NAME = "gemma4-catalog-infer-env"
INFER_ENV_VERSION = "1"
INFER_BASE_IMAGE = "mcr.microsoft.com/azureml/openmpi5.0-cuda12.4-ubuntu22.04:latest"

SCORE_SCRIPT = r'''
import json
import logging
import os
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

logger = logging.getLogger(__name__)
MODEL = None
TOKENIZER = None
MODEL_DIR = None


def _find_model_dir(root: Path) -> Path:
    if (root / "config.json").exists():
        return root
    for config_path in root.rglob("config.json"):
        return config_path.parent
    raise FileNotFoundError(f"Could not find config.json under {root}")


def init():
    global MODEL, TOKENIZER, MODEL_DIR
    root = Path(os.environ["AZUREML_MODEL_DIR"])
    MODEL_DIR = _find_model_dir(root)
    logger.info("Loading catalog model from %s", MODEL_DIR)

    TOKENIZER = AutoTokenizer.from_pretrained(MODEL_DIR, trust_remote_code=True)
    if TOKENIZER.pad_token is None:
        TOKENIZER.pad_token = TOKENIZER.eos_token

    MODEL = AutoModelForCausalLM.from_pretrained(
        MODEL_DIR,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        attn_implementation="sdpa",
    )
    MODEL.eval()
    logger.info("Catalog model init complete.")


def run(raw_data):
    payload = json.loads(raw_data) if isinstance(raw_data, (str, bytes)) else raw_data
    messages = payload.get("messages")
    prompt = payload.get("prompt")
    max_new_tokens = int(payload.get("max_new_tokens", 300))

    if messages:
        prompt = TOKENIZER.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    if not prompt:
        raise ValueError("Request must include either messages or prompt.")

    inputs = TOKENIZER(prompt, return_tensors="pt").to(MODEL.device)
    with torch.no_grad():
        output = MODEL.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=1.0,
            pad_token_id=TOKENIZER.eos_token_id,
        )

    generated = TOKENIZER.decode(output[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
    return {"response": generated, "variant": "catalog_base", "model_dir": str(MODEL_DIR)}
'''

INFER_CONDA = '''name: gemma4-catalog-infer
channels:
  - conda-forge
dependencies:
  - python=3.11
  - pip
  - pip:
      - torch==2.4.1
      - transformers>=4.51.0
      - accelerate>=1.6.0
      - sentencepiece>=0.2.0
      - protobuf>=5.28.0
      - pillow>=10.4.0
      - azureml-inference-server-http==1.2.2
'''


def ensure_environment(ml: MLClient) -> str:
    rprint(f"  Ensuring inference environment [cyan]{INFER_ENV_NAME}:{INFER_ENV_VERSION}[/cyan]...")
    try:
        env = ml.environments.get(INFER_ENV_NAME, version=INFER_ENV_VERSION)
    except Exception:
        with tempfile.TemporaryDirectory() as temp_dir:
            conda_path = Path(temp_dir) / "conda.yml"
            conda_path.write_text(INFER_CONDA)
            env = Environment(
                name=INFER_ENV_NAME,
                version=INFER_ENV_VERSION,
                image=INFER_BASE_IMAGE,
                conda_file=str(conda_path),
            )
            env = ml.environments.create_or_update(env)
    return f"{env.name}:{env.version}"


def deploy_catalog_model() -> None:
    load_project_env()
    ml = get_mlclient()

    endpoint_name = os.environ.get("ENDPOINT_NAME", DEFAULT_ENDPOINT_NAME)
    deployment_name = os.environ.get("DEPLOYMENT_NAME", DEFAULT_DEPLOYMENT_NAME)
    catalog_model_id = os.environ.get("AZUREML_CATALOG_MODEL_ID", GEMMA_CATALOG_MODEL_ID)
    model_name = os.environ.get("HF_MODEL_ID", GEMMA_MODEL_ID)

    rprint(Panel.fit("[bold]Step 04a - Deploy catalog Gemma model[/bold]"))
    rprint(f"  endpoint: [cyan]{endpoint_name}[/cyan]")
    rprint(f"  deployment: [cyan]{deployment_name}[/cyan]")
    rprint(f"  model: [cyan]{catalog_model_id}[/cyan]")

    try:
        ml.online_endpoints.get(endpoint_name)
        rprint("  endpoint exists; updating deployment")
    except Exception:
        endpoint = ManagedOnlineEndpoint(
            name=endpoint_name,
            description="Gemma catalog model hosted from Microsoft Foundry/AzureML on A100",
            auth_mode="key",
            tags={"workload": "molina-eim-finetune", "model": model_name, "source": "azureml_catalog"},
        )
        ml.online_endpoints.begin_create_or_update(endpoint).result()
        rprint("  endpoint created")

    try:
        existing_deployment = ml.online_deployments.get(name=deployment_name, endpoint_name=endpoint_name)
    except Exception:
        existing_deployment = None

    if getattr(existing_deployment, "provisioning_state", None) == "Succeeded":
        rprint(f"  deployment [cyan]{deployment_name}[/cyan] already succeeded; reusing it")
    else:
        env_ref = ensure_environment(ml)

        with tempfile.TemporaryDirectory() as temp_dir:
            score_dir = Path(temp_dir)
            (score_dir / "score.py").write_text(SCORE_SCRIPT)

            deployment = ManagedOnlineDeployment(
                name=deployment_name,
                endpoint_name=endpoint_name,
                model=catalog_model_id,
                environment=env_ref,
                code_configuration=CodeConfiguration(code=str(score_dir), scoring_script="score.py"),
                instance_type=ENDPOINT_INSTANCE_SKU,
                instance_count=1,
                environment_variables={"TRANSFORMERS_NO_ADVISORY_WARNINGS": "1"},
                request_settings=OnlineRequestSettings(request_timeout_ms=120000, max_concurrent_requests_per_instance=1),
                liveness_probe=ProbeSettings(initial_delay=600, period=30, failure_threshold=10, timeout=10),
                readiness_probe=ProbeSettings(initial_delay=600, period=30, failure_threshold=10, timeout=10),
            )

            rprint(f"\n  Creating deployment [cyan]{deployment_name}[/cyan] on [cyan]{ENDPOINT_INSTANCE_SKU}[/cyan]...")
            rprint("  This can take 10-20 minutes while AzureML builds the image and starts the A100 node.")
            try:
                ml.online_deployments.begin_create_or_update(deployment).result()
            except ResourceExistsError as exc:
                conflict_text = str(exc)
                retryable_conflict = any(
                    marker in conflict_text
                    for marker in [
                        "ConflictingConcurrentWriteNotAllowed",
                        "Already running method StartCreateDeploymentAsync",
                    ]
                )
                if not retryable_conflict:
                    raise
                rprint("  Azure reported deployment creation is already running; polling that operation.")

    terminal_states = {"Succeeded", "Failed", "Canceled"}
    last_state = None
    deployment = None
    while True:
        deployments = list(ml.online_deployments.list(endpoint_name=endpoint_name))
        deployment = next((item for item in deployments if item.name == deployment_name), None)
        state = getattr(deployment, "provisioning_state", "NotFound") if deployment else "NotFound"
        if state != last_state:
            rprint(f"  deployment state: [yellow]{state}[/yellow]")
            last_state = state
        if state in terminal_states:
            break
        time.sleep(30)

    if not deployment or deployment.provisioning_state != "Succeeded":
        raise RuntimeError(f"Catalog deployment finished with state {last_state}.")

    endpoint = ml.online_endpoints.get(endpoint_name)
    endpoint.traffic = {deployment_name: 100}
    ml.online_endpoints.begin_create_or_update(endpoint).result()
    keys = ml.online_endpoints.get_keys(endpoint_name)

    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    state.update(
        {
            "endpoint_name": endpoint_name,
            "deployment_name": deployment_name,
            "scoring_uri": endpoint.scoring_uri,
            "primary_key": keys.primary_key,
            "endpoint_mode": "catalog_base",
            "base_model": model_name,
            "base_model_asset_id": catalog_model_id,
            "endpoint_variants": ["catalog_base"],
        }
    )
    STATE_FILE.write_text(json.dumps(state, indent=2))

    rprint("\n[bold green]Catalog endpoint live.[/bold green]")
    rprint(f"  scoring URI: [dim]{endpoint.scoring_uri}[/dim]")


if __name__ == "__main__":
    deploy_catalog_model()