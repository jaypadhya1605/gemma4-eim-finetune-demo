# Molina EIM — Gemma 4B Fine-Tuning Demo (AzureML)

**Owner:** Jay Padhya (MSFT CSE) · **Customer:** Molina Healthcare EIM · **Audience:** Chirag, Dhanshri, EIM team

## What this is
Fine-tune **`google/gemma-4-E4B-it`** (Gemma 4, Effective 4B parameters, instruction-tuned) using **LoRA** on **AzureML managed compute** (A100 GPUs Chirag already has provisioned). Demonstrate before/after behavior on synthetic computer-use / extraction tasks.

The live demo is a **Streamlit split-screen app**: left side calls base Gemma 4B, right side calls the LoRA-tuned variant. Both calls go to the same A100-backed AzureML endpoint, which toggles the adapter per request so we do not pay for two hosted GPUs.

## Why this path (not Foundry serverless FT)
Foundry serverless fine-tuning does not currently list Gemma in supported base models. The only way to fine-tune Gemma 4B inside Azure today is **AzureML managed compute with your own GPU quota** — which Chirag has. This demo uses that path end-to-end.

## Why LoRA (not full fine-tune)
- **Memory:** Gemma 4B in bf16 ≈ 8 GB weights. Full FT requires ~48 GB just for params + grads + Adam state — tight on a single A100 80GB. LoRA trains ~0.1% of params; fits easily with batch size 4–8.
- **Speed:** ~30–60 minutes on 100 examples vs. several hours for full FT.
- **Cost:** ~10–20× less compute time, same hardware.
- **Production pattern:** LoRA adapters are how teams actually ship task-specific fine-tunes — you can swap adapters at inference time without redeploying base weights.

## Run order
```bash
# 0. Generate synthetic data (deterministic, no PHI)
python data/generate_synthetic_data.py

# 0a. Verify local/Azure readiness
python src/01_preflight.py

# 0b. If HF-TOKEN is not already in the workspace Key Vault, store it locally
python src/00_store_hf_token.py

# 1. Provision infra (one-time)
az deployment group create -g <rg> -f infra/main.bicep \
  --parameters workspaceName=<ws> location=eastus2 principalId=<your-objid>

# 2. Upload training + validation data to AzureML as a Data asset
python src/02_prepare_data.py

# 3. Submit the LoRA fine-tuning job (runs on A100 cluster)
python src/03_submit_training_job.py

# 4. Register the trained adapter + deploy to a managed online endpoint
python src/04_register_and_deploy.py

# 5. Demo: split-screen base Gemma 4B vs LoRA-tuned Gemma 4B
streamlit run demo_app/app.py

# 6. Optional CLI evaluation: base vs LoRA-tuned through the same endpoint
python src/05_eval.py

# 7. Tear down endpoint (also available as a Streamlit sidebar button)
python src/06_cleanup.py --yes
```

## Repo layout
```
gemma4-finetune/
├── README.md                       ← you are here
├── 00_DEMO_SCRIPT.md               ← live talk track for Chirag/Dhanshri
├── 01_setup_env.md                 ← AzureML workspace, HF token, RBAC
├── requirements.txt                ← control-plane deps (azure-ai-ml, etc.)
├── infra/
│   └── main.bicep                  ← AzureML workspace + A100 compute cluster
├── data/
│   ├── generate_synthetic_data.py  ← Deterministic synthetic dataset
│   ├── synthetic_train.jsonl       ← (generated)
│   └── synthetic_validation.jsonl  ← (generated)
├── training/
│   ├── train.py                    ← LoRA SFT script that runs ON the A100
│   └── conda.yml                   ← Environment definition for the AzureML job
├── src/
│   ├── 02_prepare_data.py          ← Upload data as AzureML Data asset
│   ├── 03_submit_training_job.py   ← Submit + monitor the training job
│   ├── 04_register_and_deploy.py   ← Register adapter, deploy online endpoint
│   ├── 05_eval.py                  ← Base vs LoRA-tuned side-by-side
│   └── 06_cleanup.py               ← Delete endpoint
├── demo_app/
│   ├── app.py                       ← Streamlit split-screen demo + endpoint controls
│   └── README.md                    ← Local app run notes
└── docs/
    ├── ARCHITECTURE.md             ← AzureML-centric architecture
    ├── RBAC_AND_QUOTA.md           ← Exactly what Chirag needs on his end
    └── RESULTS_TEMPLATE.md         ← Customer deliverable template
```

## Hard constraints (governance)
1. **No Molina data.** All training data is deterministically-generated synthetic computer-use scenarios. Zero PHI, zero real member IDs.
2. **Gemma 4 license:** Apache 2.0, but gated on Hugging Face. Need an HF token with license accepted before the training job can pull weights. See `01_setup_env.md`.
3. **All work stays in Azure.** Model weights are pulled from HF *into the A100 VM* once, training happens in-tenant, adapter artifacts land in AzureML's storage.

## Cost shape (talking points)
- **Training:** ~1 hour × NC A100 v4 list price (~$3.67/hr at time of writing, verify in Azure pricing calculator)
- **Endpoint hosting:** one A100 SKU on a managed online endpoint bills per second while the endpoint exists. The demo endpoint serves both base and fine-tuned variants by toggling the LoRA adapter per request. Always delete it from Streamlit or run step 07.
- **Inference cost story for production:** a deployed LoRA-tuned Gemma 4B on a single A100 can serve thousands of requests/min at fraction of frontier-model per-token cost — but you eat the hourly VM cost regardless of traffic, so the breakeven is around tens of thousands of calls/day.
