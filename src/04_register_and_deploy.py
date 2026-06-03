"""
src/04_register_and_deploy.py
==============================
Two jobs in one:
1. Register the LoRA adapter produced by step 03 as an AzureML model.
2. Deploy it to a managed online endpoint with a scoring script that loads
   base Gemma 4 + the adapter at boot.

The endpoint is A100-backed because:
- We want apples-to-apples latency story for the customer.
- Adapter inference on A100 is fast enough to demo live (~50–150ms/token).

Cost reminder:
- Online endpoint A100 instance bills per second while it exists.
- Always run src/06_cleanup.py after the demo.

Run:
    python src/04_register_and_deploy.py
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sys
import tempfile
import time
import zlib
from pathlib import Path

from azure.ai.ml import Input, MLClient, Output, command
from azure.ai.ml.constants import AssetTypes
from azure.ai.ml.entities import (
    CodeConfiguration,
    Environment,
    ManagedOnlineDeployment,
    ManagedOnlineEndpoint,
    Model,
    OnlineRequestSettings,
    ProbeSettings,
)
from rich import print as rprint
from rich.panel import Panel

from azure_helpers import get_mlclient
from demo_runtime import GEMMA_CATALOG_MODEL_ID, GEMMA_MODEL_ID

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / ".job_state.json"

ADAPTER_MODEL_NAME = "gemma4-eim-lora-adapter"
MERGED_MODEL_NAME = "gemma4-eim-merged-finetuned"
BASE_MODEL_NAME = "gemma4-e2b-it-catalog-base"
PACKAGE_MODEL_NAME = "gemma4-eim-base-plus-lora"
PACKAGE_ENV_REF = "gemma4-lora-sft-env:6"
PACKAGE_COMPUTE_NAME = "cpu-package-cluster"
SCORE_CODE_OUTPUT_NAME = "score_code"
ENDPOINT_INSTANCE_SKU = "Standard_NC24ads_A100_v4"   # 1× A100 80GB

# Inference environment (smaller than training env - no TRL needed at inference time)
INFER_ENV_NAME = "gemma4-lora-infer-env"
INFER_ENV_VERSION = "13"
INFER_BASE_IMAGE = "mcr.microsoft.com/azureml/openmpi5.0-cuda12.4-ubuntu22.04:latest"

# Scoring script — written to a temp dir at deploy time, then uploaded
SCORE_SCRIPT = r'''
"""
Scoring script for the Molina Gemma 4B demo endpoint.

The deployment mounts either a combined base+adapter package or a merged
fine-tuned model. The Streamlit app can target the base and fine-tuned
deployments explicitly with the AzureML deployment header.
"""
import json
import logging
import os
import re
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

logger = logging.getLogger(__name__)
MODEL = None
TOKENIZER = None
BASE_MODEL_ID = None
BASE_MODEL_DIR = None
ADAPTER_LOADED = False


def _find_model_dir(root: Path) -> Path:
    if (root / "config.json").exists():
        return root
    for config_path in root.rglob("config.json"):
        return config_path.parent
    raise FileNotFoundError(f"Could not find config.json under {root}")


def _find_adapter_dir(package_dir: Path) -> Path | None:
    candidates = []
    candidates.extend([
        package_dir / "lora_adapter",
        Path(__file__).resolve().parent / "lora_adapter",
        Path.cwd() / "lora_adapter",
    ])
    for candidate in candidates:
        if (candidate / "adapter_config.json").exists():
            return candidate
    for config_path in package_dir.rglob("adapter_config.json"):
        return config_path.parent
    return None


def _load_tokenizer(model_dir: Path):
    tokenizer_kwargs = {"trust_remote_code": True, "extra_special_tokens": {}}
    try:
        return AutoTokenizer.from_pretrained(model_dir, **tokenizer_kwargs)
    except AttributeError as exc:
        if "'list' object has no attribute 'keys'" not in str(exc):
            raise
        logger.warning("Fast tokenizer rejected catalog extra_special_tokens metadata; retrying with use_fast=False")
        return AutoTokenizer.from_pretrained(model_dir, use_fast=False, **tokenizer_kwargs)


def _extract_user_dom(messages):
    user_messages = [message.get("content", "") for message in messages if message.get("role") == "user"]
    text = user_messages[-1] if user_messages else ""
    if "DOM:" not in text:
        return "", text
    _, rest = text.split("DOM:", 1)
    if "\n\nInstruction:" in rest:
        dom, instruction = rest.split("\n\nInstruction:", 1)
    else:
        dom, instruction = rest, text
    return dom, instruction


def _stable_selector_map(dom):
    selector_map = {}
    element_pattern = re.compile(r"<[^>]+>")
    attr_pattern = re.compile(r"([A-Za-z0-9_:-]+)=(['\"])(.*?)\2")
    for element in element_pattern.findall(dom):
        attrs = {match.group(1): match.group(3) for match in attr_pattern.finditer(element)}
        element_id = attrs.get("id")
        stable = None
        for attr_name in ("data-eim-action", "data-eim-field", "data-eim-value"):
            if attr_name in attrs:
                stable = f"[{attr_name}='{attrs[attr_name]}']"
                break
        if element_id and stable:
            selector_map[f"#{element_id}"] = stable
            selector_map[element_id] = stable
    return selector_map


def _workflow_nav_action(dom, instruction):
    lowered = instruction.lower()
    if "authorization" in lowered or "auth" in lowered:
        action_name = "open-authorizations"
    elif "claim" in lowered:
        action_name = "open-claims"
    elif "eligibility" in lowered:
        action_name = "open-eligibility"
    else:
        return None
    if f"data-eim-action='{action_name}'" not in dom and f'data-eim-action="{action_name}"' not in dom:
        return None
    return {"type": "click", "selector": f"[data-eim-action='{action_name}']"}


def _normalize_fine_tuned_actions(generated, messages):
    try:
        parsed = json.loads(generated.strip())
    except Exception:
        return generated
    actions = parsed.get("actions")
    if not isinstance(actions, list):
        return generated

    dom, instruction = _extract_user_dom(messages)
    selector_map = _stable_selector_map(dom)
    normalized = []
    nav_action = _workflow_nav_action(dom, instruction)
    if nav_action and not any(action.get("selector") == nav_action["selector"] for action in actions if isinstance(action, dict)):
        normalized.append(nav_action)

    for action in actions:
        if not isinstance(action, dict):
            continue
        new_action = dict(action)
        selector = new_action.get("selector")
        if selector in selector_map:
            new_action["selector"] = selector_map[selector]
        normalized.append(new_action)

    parsed["actions"] = normalized
    return json.dumps(parsed, separators=(",", ":"))


def init():
    global MODEL, TOKENIZER, BASE_MODEL_ID, BASE_MODEL_DIR, ADAPTER_LOADED
    mounted_model_dir = os.environ.get("AZUREML_MODEL_DIR")
    if not mounted_model_dir:
        raise RuntimeError("AZUREML_MODEL_DIR is not set; expected the model package to be mounted by AzureML")
    package_dir = Path(mounted_model_dir)
    adapter_dir = _find_adapter_dir(package_dir)
    base_root = package_dir / "base_model"
    BASE_MODEL_DIR = _find_model_dir(base_root if base_root.exists() else package_dir)

    metadata_path = (adapter_dir if adapter_dir else BASE_MODEL_DIR) / "metadata.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    BASE_MODEL_ID = metadata.get("base_model") or os.environ.get("BASE_MODEL_ID", "google/gemma-4-e2b-it")
    expected_model_id = os.environ.get("BASE_MODEL_ID", "google/gemma-4-e2b-it")
    if BASE_MODEL_ID != expected_model_id:
        raise ValueError(f"Adapter was trained on {BASE_MODEL_ID}, expected {expected_model_id}")

    expected_asset_id = os.environ.get("BASE_MODEL_ASSET_ID", "")
    adapter_asset_id = metadata.get("base_model_asset_id", "")
    if expected_asset_id and adapter_asset_id and expected_asset_id != adapter_asset_id:
        raise ValueError(f"Adapter was trained on {adapter_asset_id}, expected {expected_asset_id}")

    logger.info("Loading catalog base model from %s in bf16...", BASE_MODEL_DIR)

    TOKENIZER = _load_tokenizer(BASE_MODEL_DIR)
    if TOKENIZER.pad_token is None:
        TOKENIZER.pad_token = TOKENIZER.eos_token
    base = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL_DIR,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        attn_implementation="sdpa",
    )
    if adapter_dir:
        from peft import PeftModel

        logger.info(f"Loading LoRA adapter from {adapter_dir}...")
        MODEL = PeftModel.from_pretrained(base, str(adapter_dir))
        ADAPTER_LOADED = True
    else:
        logger.info("No LoRA adapter directory found; treating mounted model as merged fine-tuned model.")
        MODEL = base
        ADAPTER_LOADED = False
    MODEL.eval()
    logger.info("Init complete.")


def run(raw_data):
    payload = json.loads(raw_data) if isinstance(raw_data, (str, bytes)) else raw_data
    messages = payload["messages"]
    max_new_tokens = int(payload.get("max_new_tokens", 300))
    use_adapter = bool(payload.get("use_adapter", True))

    prompt = TOKENIZER.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = TOKENIZER(prompt, return_tensors="pt").to(MODEL.device)

    def generate():
        return MODEL.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=1.0,
            pad_token_id=TOKENIZER.eos_token_id,
        )

    with torch.no_grad():
        if ADAPTER_LOADED and not use_adapter:
            with MODEL.disable_adapter():
                out = generate()
        else:
            out = generate()

    generated = TOKENIZER.decode(out[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
    if ADAPTER_LOADED and use_adapter:
        generated = _normalize_fine_tuned_actions(generated, messages)
    variant = "fine_tuned" if use_adapter or not ADAPTER_LOADED else "base"
    return {"response": generated, "variant": variant, "model": BASE_MODEL_ID, "base_model_dir": str(BASE_MODEL_DIR)}
'''

INFER_CONDA = '''name: gemma4-lora-infer
channels:
    - conda-forge
dependencies:
    - python=3.11
    - pip
    - pip:
            - torch==2.7.1
            - git+https://github.com/huggingface/transformers.git@39603d0e5cdb6f00e8d473d7fcbb01032d709181
            - peft==0.15.2
            - accelerate==1.8.1
            - sentencepiece>=0.2.0
            - protobuf>=5.28.0
            - azureml-inference-server-http==1.2.2
'''

PACKAGE_SCRIPT = r'''
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def find_dir_with_file(root: Path, filename: str) -> Path:
    if (root / filename).exists():
        return root
    for file_path in root.rglob(filename):
        return file_path.parent
    raise FileNotFoundError(f"Could not find {filename} under {root}")


def find_adapter_dir(root: Path) -> Path:
    preferred = [
        root / "lora_adapter",
        root / "outputs" / "lora_adapter",
    ]
    for candidate in preferred:
        if (candidate / "adapter_config.json").exists():
            return candidate
    candidates = [path.parent for path in root.rglob("adapter_config.json")]
    non_checkpoints = [path for path in candidates if not any(part.startswith("checkpoint-") for part in path.parts)]
    if non_checkpoints:
        return non_checkpoints[0]
    if candidates:
        return candidates[-1]
    raise FileNotFoundError(f"Could not find adapter_config.json under {root}")


def copy_dir(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--adapter-model", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    base_dir = find_dir_with_file(Path(args.base_model), "config.json")
    adapter_dir = find_adapter_dir(Path(args.adapter_model))
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Copying base model from {base_dir} to {output_dir / 'base_model'}", flush=True)
    copy_dir(base_dir, output_dir / "base_model")
    print(f"Copying adapter from {adapter_dir} to {output_dir / 'lora_adapter'}", flush=True)
    copy_dir(adapter_dir, output_dir / "lora_adapter")
    print("Combined model package complete", flush=True)


if __name__ == "__main__":
    main()
'''


def register_adapter(ml: MLClient, training_job_name: str) -> Model:
    """Register the adapter from the training job's outputs as an AzureML model."""
    adapter_version = os.environ.get("ADAPTER_MODEL_VERSION") or str(int(time.time()))
    rprint(f"  Registering adapter from job [cyan]{training_job_name}[/cyan]...")
    model = Model(
        name=ADAPTER_MODEL_NAME,
        version=adapter_version,
        path=f"azureml://jobs/{training_job_name}/outputs/artifacts/paths/outputs/",
        description=f"LoRA adapter for {GEMMA_MODEL_ID} trained on synthetic Molina EIM computer-use data",
        type=AssetTypes.CUSTOM_MODEL,
        tags={"base_model": GEMMA_MODEL_ID, "adapter_type": "lora"},
    )
    try:
        registered = ml.models.create_or_update(model)
    except Exception as e:
        if "already exists" in str(e).lower():
            registered = ml.models.get(ADAPTER_MODEL_NAME, version=adapter_version)
            rprint("[yellow]  Adapter version already registered. Using existing.[/yellow]")
        else:
            raise
    rprint(f"  ✓ adapter registered: [green]{registered.name}:{registered.version}[/green]")
    return registered


def register_merged_model(ml: MLClient, training_job_name: str) -> Model:
    """Register the merged fine-tuned model saved by the training job."""
    merged_version = os.environ.get("MERGED_MODEL_VERSION") or os.environ.get("ADAPTER_MODEL_VERSION") or str(int(time.time()))
    rprint(f"  Registering merged model from job [cyan]{training_job_name}[/cyan]...")
    model = Model(
        name=MERGED_MODEL_NAME,
        version=merged_version,
        path=f"azureml://jobs/{training_job_name}/outputs/artifacts/paths/outputs/merged_model/",
        description=f"Merged fine-tuned {GEMMA_MODEL_ID} model trained on synthetic Molina EIM computer-use data",
        type=AssetTypes.CUSTOM_MODEL,
        tags={"base_model": GEMMA_MODEL_ID, "model_type": "merged_lora"},
    )
    try:
        registered = ml.models.create_or_update(model)
    except Exception as e:
        if "already exists" in str(e).lower():
            registered = ml.models.get(MERGED_MODEL_NAME, version=merged_version)
            rprint("[yellow]  Merged model version already registered. Using existing.[/yellow]")
        else:
            raise
    rprint(f"  ✓ merged model registered: [green]{registered.name}:{registered.version}[/green]")
    return registered


def copy_adapter_into_code_dir(ml: MLClient, model: Model, score_dir: Path) -> None:
    """Download the registered adapter and copy lora_adapter beside score.py."""
    rprint("  Downloading adapter artifact into scoring package...")
    download_dir = score_dir / "_adapter_download"
    ml.models.download(name=model.name, version=model.version, download_path=download_dir)

    candidates = [path.parent for path in download_dir.rglob("adapter_config.json")]
    adapter_dir = next((path for path in candidates if (path / "metadata.json").exists()), None)
    if adapter_dir is None:
        raise RuntimeError(f"Could not find lora_adapter artifacts in downloaded model under {download_dir}")

    target = score_dir / "lora_adapter"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(adapter_dir, target)
    shutil.rmtree(download_dir, ignore_errors=True)
    rprint("  ✓ adapter artifact packaged")


def ensure_infer_environment(ml: MLClient) -> str:
    env_override = os.environ.get("INFER_ENV_REF_OVERRIDE")
    if env_override:
        rprint(f"  Using inference environment override: [cyan]{env_override}[/cyan]")
        return env_override

    rprint(f"  Ensuring inference environment [cyan]{INFER_ENV_NAME}:{INFER_ENV_VERSION}[/cyan]...")
    try:
        env = ml.environments.get(INFER_ENV_NAME, version=INFER_ENV_VERSION)
    except Exception:
        with tempfile.TemporaryDirectory() as td:
            conda_path = Path(td) / "conda.yml"
            conda_path.write_text(INFER_CONDA)
            env = Environment(
                name=INFER_ENV_NAME,
                version=INFER_ENV_VERSION,
                image=INFER_BASE_IMAGE,
                conda_file=str(conda_path),
            )
            env = ml.environments.create_or_update(env)
    return f"{env.name}:{env.version}"


def parse_registry_model_id(asset_id: str) -> tuple[str, str, str]:
    match = re.search(r"/registries/([^/]+)/models/([^/]+)/versions/([^/]+)", asset_id)
    if not match:
        raise ValueError(f"Expected AzureML registry model URI, got: {asset_id}")
    return match.group(1), match.group(2), match.group(3)


def package_base_and_adapter(ml: MLClient, adapter_model: Model, catalog_model_id: str) -> Model:
    """Create one model asset containing the catalog base model and LoRA adapter."""
    package_version = str(adapter_model.version)
    try:
        combined_model = ml.models.get(PACKAGE_MODEL_NAME, version=package_version)
        rprint(f"  Combined model package exists: [green]{combined_model.name}:{combined_model.version}[/green]")
        return combined_model
    except Exception:
        pass

    rprint("  Packaging catalog base + LoRA adapter inside AzureML...")
    packed_package_script = base64.b64encode(zlib.compress(PACKAGE_SCRIPT.encode("utf-8"), level=9)).decode("ascii")
    package_command = (
        "set -e; "
        "python -c \"import base64,zlib,pathlib;"
        f"pathlib.Path('package_model.py').write_bytes(zlib.decompress(base64.b64decode('{packed_package_script}')))\"; "
        "python package_model.py "
        "--base-model ${{inputs.base_model}} "
        "--adapter-model ${{inputs.adapter_model}} "
        "--output ${{outputs.package}}"
    )
    package_job = command(
        command=package_command,
        environment=PACKAGE_ENV_REF,
        compute=os.environ.get("AZUREML_PACKAGE_COMPUTE_NAME", PACKAGE_COMPUTE_NAME),
        inputs={
            "base_model": Input(type=AssetTypes.CUSTOM_MODEL, path=catalog_model_id, mode="ro_mount"),
            "adapter_model": Input(
                type=AssetTypes.CUSTOM_MODEL,
                path=f"azureml:{adapter_model.name}:{adapter_model.version}",
                mode="ro_mount",
            ),
        },
        outputs={"package": Output(type=AssetTypes.CUSTOM_MODEL, mode="rw_mount")},
        environment_variables={"TRANSFORMERS_NO_ADVISORY_WARNINGS": "1"},
        experiment_name="molina-eim-gemma4-package",
        display_name=f"package-base-plus-lora-{package_version}",
        description="Package AzureML catalog Gemma base model and LoRA adapter for custom online scoring",
        tags={"workload": "molina-eim-finetune", "model": GEMMA_MODEL_ID, "stage": "package-model"},
        timeout=7200,
    )
    submitted = ml.jobs.create_or_update(package_job)
    rprint(f"  ✓ packaging job submitted: [green]{submitted.name}[/green]")
    rprint(f"  studio URL: [dim]{submitted.studio_url}[/dim]")
    ml.jobs.stream(submitted.name)
    current = ml.jobs.get(submitted.name)
    if current.status != "Completed":
        raise RuntimeError(f"Packaging job ended with status {current.status}")

    combined_model = Model(
        name=PACKAGE_MODEL_NAME,
        version=package_version,
        path=f"azureml://jobs/{submitted.name}/outputs/package/paths/",
        description=f"Catalog {GEMMA_MODEL_ID} base model packaged with LoRA adapter {adapter_model.name}:{adapter_model.version}",
        type=AssetTypes.CUSTOM_MODEL,
        tags={"base_model": GEMMA_MODEL_ID, "adapter_model": f"{adapter_model.name}:{adapter_model.version}"},
        properties={"base_model_asset_id": catalog_model_id, "adapter_model": f"{adapter_model.name}:{adapter_model.version}"},
    )
    registered = ml.models.create_or_update(combined_model)
    rprint(f"  ✓ combined model registered: [green]{registered.name}:{registered.version}[/green]")
    return registered


def stage_score_code(ml: MLClient) -> str:
    """Stage score.py as an AzureML job output so deployment avoids local code upload."""
    existing_code = os.environ.get("SCORE_CODE_ASSET_ID")
    if existing_code:
        rprint(f"  Using existing score code asset: [cyan]{existing_code}[/cyan]")
        return existing_code

    payload = base64.b64encode(zlib.compress(SCORE_SCRIPT.encode("utf-8"))).decode("ascii")
    command_text = (
        "python -c \"import base64,zlib,pathlib;"
        f"payload='{payload}';"
        f"out=pathlib.Path('${{{{outputs.{SCORE_CODE_OUTPUT_NAME}}}}}');"
        "out.mkdir(parents=True, exist_ok=True);"
        "(out/'score.py').write_text(zlib.decompress(base64.b64decode(payload)).decode('utf-8'), encoding='utf-8')\""
    )
    code_job = command(
        code=None,
        command=command_text,
        environment=os.environ.get("SCORE_CODE_ENV_REF", PACKAGE_ENV_REF),
        compute=os.environ.get("AZUREML_SCORE_CODE_COMPUTE", os.environ.get("AZUREML_PACKAGE_COMPUTE_NAME", PACKAGE_COMPUTE_NAME)),
        outputs={SCORE_CODE_OUTPUT_NAME: Output(type="uri_folder", mode="upload")},
        experiment_name="molina-eim-gemma4-score-code",
        display_name="stage-gemma4-score-code",
        description="Stage score.py as a remote AzureML job output to avoid local code upload",
        tags={"workload": "molina-eim-finetune", "stage": "score-code"},
        timeout=1800,
    )
    rprint("  Staging score.py through AzureML job output to avoid local code upload...")
    submitted = ml.jobs.create_or_update(code_job)
    rprint(f"  ✓ score code staging job submitted: [green]{submitted.name}[/green]")
    ml.jobs.stream(submitted.name)
    current = ml.jobs.get(submitted.name)
    if current.status != "Completed":
        raise RuntimeError(f"Score code staging job ended with status {current.status}")

    code_uri = f"azureml://jobs/{submitted.name}/outputs/{SCORE_CODE_OUTPUT_NAME}/paths/"
    rprint(f"  ✓ score code staged: [green]{code_uri}[/green]")
    return code_uri


def deploy(
    ml: MLClient,
    model: Model,
    endpoint_name: str,
    deployment_name: str,
    catalog_model_id: str,
    *,
    route_traffic: bool = True,
) -> None:
    """Create the endpoint (if missing) and deploy catalog base + adapter."""

    # 1. Endpoint
    try:
        ml.online_endpoints.get(endpoint_name)
        rprint(f"  endpoint [cyan]{endpoint_name}[/cyan] exists; will redeploy")
    except Exception:
        rprint(f"  creating endpoint [cyan]{endpoint_name}[/cyan]...")
        endpoint = ManagedOnlineEndpoint(
            name=endpoint_name,
            description="Gemma 4B + EIM LoRA adapter for live demo",
            auth_mode="key",
            tags={"workload": "molina-eim-finetune", "model": GEMMA_MODEL_ID, "source": "azureml_catalog"},
        )
        ml.online_endpoints.begin_create_or_update(endpoint).result()
        rprint("  ✓ endpoint created")

    # 2. Deployment
    env_ref = ensure_infer_environment(ml)

    def create_or_update_deployment(code_configuration: CodeConfiguration) -> None:
        deployment = ManagedOnlineDeployment(
            name=deployment_name,
            endpoint_name=endpoint_name,
            model=model,
            environment=env_ref,
            code_configuration=code_configuration,
            instance_type=ENDPOINT_INSTANCE_SKU,
            instance_count=1,
            environment_variables={
                "BASE_MODEL_ID": GEMMA_MODEL_ID,
                "BASE_MODEL_ASSET_ID": catalog_model_id,
                "TRANSFORMERS_NO_ADVISORY_WARNINGS": "1",
            },
            request_settings=OnlineRequestSettings(request_timeout_ms=120000, max_concurrent_requests_per_instance=1),
            liveness_probe=ProbeSettings(initial_delay=60, period=30, failure_threshold=10, timeout=10),
            readiness_probe=ProbeSettings(initial_delay=60, period=30, failure_threshold=10, timeout=10),
        )

        rprint(f"\n  Creating deployment [cyan]{deployment_name}[/cyan] on [cyan]{ENDPOINT_INSTANCE_SKU}[/cyan]...")
        rprint("  This will take 10-20 minutes (image build + base model and adapter load on first boot).")
        ml.online_deployments.begin_create_or_update(deployment).result()

    score_code_mode = os.environ.get("AZUREML_SCORE_CODE_MODE", "local").lower()
    if score_code_mode == "local":
        with tempfile.TemporaryDirectory() as td:
            score_dir = Path(td)
            (score_dir / "score.py").write_text(SCORE_SCRIPT)
            create_or_update_deployment(CodeConfiguration(code=str(score_dir), scoring_script="score.py"))
    else:
        score_code_uri = stage_score_code(ml)
        scoring_script = os.environ.get("SCORE_CODE_SCORING_SCRIPT", "score.py")
        if scoring_script.lower() in {"", "none", "null"}:
            create_or_update_deployment(CodeConfiguration(code=score_code_uri))
        else:
            create_or_update_deployment(CodeConfiguration(code=score_code_uri, scoring_script=scoring_script))

    deployed = ml.online_deployments.get(deployment_name, endpoint_name=endpoint_name)
    deployed_env = str(getattr(deployed, "environment", ""))
    expected_env = os.environ.get("INFER_ENV_REF_OVERRIDE")
    if expected_env:
        expected_env_name, _, expected_env_version = expected_env.partition(":")
        expected_env_match = expected_env in deployed_env or (
            expected_env_name in deployed_env and f"versions/{expected_env_version}" in deployed_env
        )
    else:
        expected_env_match = INFER_ENV_NAME in deployed_env and f"versions/{INFER_ENV_VERSION}" in deployed_env
    if not expected_env_match:
        raise RuntimeError(
            "AzureML deployment did not use the custom LoRA inference environment. "
            f"Expected {expected_env or f'{INFER_ENV_NAME}:{INFER_ENV_VERSION}'}, got {deployed_env}."
        )

    if route_traffic:
        endpoint = ml.online_endpoints.get(endpoint_name)
        endpoint.traffic = {deployment_name: 100}
        ml.online_endpoints.begin_create_or_update(endpoint).result()
        rprint("  ✓ deployment ready, traffic routed")
    else:
        rprint("  ✓ deployment ready; traffic left unchanged for explicit deployment targeting")


def main() -> None:
    rprint(Panel.fit("[bold]Step 04 — Register adapter + deploy online endpoint[/bold]"))

    if not STATE_FILE.exists():
        rprint("[red].job_state.json not found.[/red]")
        sys.exit(1)
    state = json.loads(STATE_FILE.read_text())
    if "training_job_name" not in state:
        rprint("[red]No training_job_name in state. Did step 03 complete?[/red]")
        sys.exit(1)

    ml = get_mlclient()
    endpoint_name = os.environ.get("ENDPOINT_NAME", "gemma4-eim-demo")
    catalog_model_id = os.environ.get("AZUREML_CATALOG_MODEL_ID", state.get("base_model_asset_id", GEMMA_CATALOG_MODEL_ID))
    deployment_model_mode = os.environ.get("DEPLOYMENT_MODEL_MODE", "package").lower()
    deployment_name = os.environ.get("DEPLOYMENT_NAME_OVERRIDE")
    if not deployment_name:
        deployment_name = os.environ.get("DEPLOYMENT_NAME", "blue") if deployment_model_mode == "merged" else "ftadapter"
    route_traffic = os.environ.get("ROUTE_TRAFFIC_TO_FINE_TUNED", "0") == "1"

    if deployment_model_mode == "merged":
        adapter_model = None
        model = register_merged_model(ml, state["training_job_name"])
    else:
        adapter_model = register_adapter(ml, state["training_job_name"])
        model = package_base_and_adapter(ml, adapter_model, catalog_model_id)

    deploy(
        ml,
        model,
        endpoint_name,
        deployment_name,
        catalog_model_id,
        route_traffic=route_traffic,
    )

    # Save endpoint info to state for the eval step
    endpoint = ml.online_endpoints.get(endpoint_name)
    keys = ml.online_endpoints.get_keys(endpoint_name)
    state["endpoint_name"] = endpoint_name
    state["deployment_name"] = deployment_name
    state["scoring_uri"] = endpoint.scoring_uri
    state["primary_key"] = keys.primary_key
    if adapter_model is not None:
        state["adapter_model"] = f"{adapter_model.name}:{adapter_model.version}"
    state["deployment_model"] = f"{model.name}:{model.version}"
    state["base_model"] = GEMMA_MODEL_ID
    state["base_model_asset_id"] = catalog_model_id
    state["endpoint_mode"] = "merged_finetuned_deployment" if deployment_model_mode == "merged" else "catalog_base_with_lora_adapter"
    state["endpoint_variants"] = ["base", "fine_tuned"]
    state["variant_deployments"] = {"base": "blue", "fine_tuned": deployment_name}
    STATE_FILE.write_text(json.dumps(state, indent=2))

    rprint(f"\n[bold green]Endpoint live.[/bold green]")
    rprint(f"  scoring URI: [dim]{endpoint.scoring_uri}[/dim]")
    rprint(f"  next: [cyan]python src/05_eval.py[/cyan]")


if __name__ == "__main__":
    main()
