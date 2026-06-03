# Architecture — Gemma 4B LoRA Fine-Tune on AzureML

## Logical view

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Subscription / RG                              │
│                                                                         │
│  ┌─────────────┐    ┌──────────────────────────────────────────────┐   │
│  │ Key Vault   │◄───│       AzureML Workspace                       │   │
│  │  HF_TOKEN   │    │                                               │   │
│  └─────────────┘    │  ┌─────────────────────────────────────────┐  │   │
│                     │  │ Data asset (URI_FOLDER)                  │  │   │
│  ┌─────────────┐    │  │  - synthetic_train.jsonl                 │  │   │
│  │ Storage     │◄───│  │  - synthetic_validation.jsonl            │  │   │
│  │ (default DS)│    │  └─────────────────────────────────────────┘  │   │
│  └─────────────┘    │                       │                        │   │
│                     │                       │ ro_mount               │   │
│  ┌─────────────┐    │                       ▼                        │   │
│  │ App Insights│◄───│  ┌─────────────────────────────────────────┐  │   │
│  │ (endpoint   │    │  │ Training job (command)                   │  │   │
│  │  telemetry) │    │  │  compute: a100-cluster-1node             │  │   │
│  └─────────────┘    │  │  env:     gemma4-lora-sft-env            │  │   │
│                     │  │  code:    training/train.py              │  │   │
│                     │  │  HF_TOKEN env var                        │  │   │
│                     │  │                                           │  │   │
│                     │  │  ┌────────────────────┐                  │  │   │
│                     │  │  │ A100 80GB node     │                  │  │   │
│                     │  │  │ - load Gemma 4 bf16│                  │  │   │
│                     │  │  │ - LoRA r=16        │                  │  │   │
│                     │  │  │ - TRL SFTTrainer   │                  │  │   │
│                     │  │  │ - save adapter     │                  │  │   │
│                     │  │  └────────────────────┘                  │  │   │
│                     │  └──────────┬──────────────────────────────┘  │   │
│                     │             │ outputs/lora_adapter/             │   │
│                     │             ▼                                   │   │
│                     │  ┌─────────────────────────────────────────┐  │   │
│                     │  │ Registered Model                         │  │   │
│                     │  │  gemma4-eim-lora-adapter:1               │  │   │
│                     │  └──────────┬──────────────────────────────┘  │   │
│                     │             │                                   │   │
│                     │             ▼                                   │   │
│                     │  ┌─────────────────────────────────────────┐  │   │
│                     │  │ Managed Online Endpoint                  │  │   │
│                     │  │  gemma4-eim-demo                         │  │   │
│                     │  │  ┌─────────────────────────────────────┐ │  │   │
│                     │  │  │ blue deployment (100% traffic)       │ │  │   │
│                     │  │  │  - Standard_NC24ads_A100_v4          │ │  │   │
│                     │  │  │  - score.py loads base + adapter     │ │  │   │
│                     │  │  │  - request toggles use_adapter       │ │  │   │
│                     │  │  └─────────────────────────────────────┘ │  │   │
│                     │  └─────────────────────────────────────────┘  │   │
│                     └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘

           ▲                                          ▲
           │ AAD                                      │ Bearer key
           │ DefaultAzureCredential                   │
   ┌───────┴──────────┐                       ┌───────┴──────────┐
   │ Control plane    │                       │ Eval / customer  │
   │ (Jay's laptop)   │                       │ (eval calls)     │
    │ src/0[2-6]_*.py  │                       │ demo_app + 05    │
   └──────────────────┘                       └──────────────────┘
```

## Why each piece is here

| Component | Role |
|---|---|
| AzureML workspace | The unit of governance, RBAC, and asset registration |
| Storage account | Default datastore — backs the data asset and job artifacts |
| Key Vault | Holds `HF_TOKEN` for gated Gemma access. RBAC-controlled. |
| App Insights + Log Analytics | Endpoint telemetry, latency p50/p95/p99, error rates |
| A100 compute cluster | The actual GPU. Auto-scales 0↔1 — only pays when training |
| Data asset (URI_FOLDER) | Versioned reference to the synthetic JSONL. Mounted RO into the job |
| Training job | `command` job that runs `train.py`. Pulls Gemma weights, fits LoRA, writes adapter |
| Registered model | Captures the adapter + metadata for deployment + audit trail |
| Managed online endpoint | Serves base and fine-tuned variants from one A100-backed deployment by toggling LoRA per request |

## Data flow during the demo

1. **Data generation:** `data/generate_synthetic_data.py` on the laptop produces JSONL. No network.
2. **Data upload:** `src/02_prepare_data.py` registers `gemma4-eim-synthetic:1` as a Data asset. The JSONL files land in the workspace's default datastore.
3. **Training:** `src/03_submit_training_job.py` submits a `command` job. The job:
    - Mounts the data asset read-only.
    - Pulls `google/gemma-4-E4B-it` from Hugging Face (using `HF_TOKEN` env).
    - Wraps it in a LoRA config targeting attention + MLP projections.
    - TRL's `SFTTrainer` applies Gemma's chat template per record and trains.
    - Writes adapter to `./outputs/lora_adapter/`. AzureML automatically uploads `./outputs/` as job artifacts.
4. **Registration + deploy:** `src/04_register_and_deploy.py`:
    - Registers the adapter as `gemma4-eim-lora-adapter:1` (model type: custom).
    - Creates the managed online endpoint + blue deployment with `score.py` that loads base + adapter at boot.
    - Requests use `use_adapter=false` for base Gemma 4B and `use_adapter=true` for the LoRA-tuned variant.
    - First-time boot is slow (10–20 min) due to weight download. Subsequent restarts are faster.
5. **Demo/eval:** `demo_app/app.py` and `src/05_eval.py` hit the same endpoint twice per prompt and compare base vs fine-tuned behavior.
6. **Cleanup:** the Streamlit sidebar or `src/06_cleanup.py` deletes the endpoint. Compute cluster auto-scales to 0 on its own.

## Security / governance properties

- **AAD-only auth on control plane** via `DefaultAzureCredential`. No service-principal secrets in code.
- **HF_TOKEN in Key Vault** (production setup). For the demo it's passed via env var; the comment in `03_submit_training_job.py` describes the Key Vault wiring.
- **Endpoint auth:** key-based for the demo. Switch to `aml_token` in production for short-lived AAD tokens.
- **Synthetic data only.** No Molina-tenant data ever touches this subscription.
- **Audit trail:** every job, data asset version, and model version is captured in AzureML's lineage view.

## Production hardening (talking points)

- VNet-attached workspace + private endpoints on storage, KV, AppInsights, and the workspace itself
- Customer-managed keys on the storage account
- Online endpoint behind APIM for centralized rate limiting + auth normalization
- Multi-deployment (blue/green) for safe rolling updates of new adapter versions
- AzureML pipelines for CI: new synthetic data → SFT → automated eval gate → register → deploy (manual approval optional)
- Switch to a multi-adapter serving setup (vLLM with LoRA hot-swap) when you have several adapters for different EIM workflows — saves having one A100 per adapter
