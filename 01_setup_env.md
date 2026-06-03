# 01 — Environment Setup

## Prerequisites
- **Azure subscription** with **quota for at least 1× `Standard_NC24ads_A100_v4` (1× A100 80GB)** in your chosen region (preferred: eastus2 or southcentralus)
- **AzureML workspace** (provisioned by `infra/main.bicep`)
- **Hugging Face account** with:
  - HF access token (read-scope is enough)
  - **Gemma 4 license accepted** on `https://huggingface.co/google/gemma-4-E4B-it` (one-click; required because Gemma is gated)
- **Python 3.10, 3.11, or 3.12** on your control-plane workstation (the workstation just submits jobs — actual training runs in AzureML). Avoid Python 3.13/3.14 for this demo until AzureML, Streamlit, and PyArrow publish complete wheels for your platform.
- **Azure CLI** logged in: `az login --tenant <tid> && az account set --subscription <subid>`

If Microsoft Non-Production Conditional Access blocks device-code sign-in with "device requesting access must be managed," first try the VS Code Azure extension sign-in and set `AZURE_AUTH_MODE=vscode`. If that is also blocked, run the control plane from a compliant Microsoft Non-Production managed device, a compliant jump box/dev box, or use service-principal auth. For service-principal auth, set `AZURE_AUTH_MODE=service_principal` and fill `AZURE_CLIENT_ID` plus `AZURE_CLIENT_SECRET` locally in `.env`. Do not paste the secret into chat.

## RBAC roles needed
| Action | Role | Scope |
|---|---|---|
| Submit AzureML jobs | `AzureML Data Scientist` | Workspace |
| Create + delete online endpoints | `AzureML Compute Operator` + `Contributor` | Workspace |
| Deploy infrastructure (one-time) | `Contributor` | Resource Group |
| Access Key Vault for HF token | `Key Vault Secrets User` | Key Vault under the workspace |

Chirag's existing A100 quota is the bottleneck. Verify with:
```bash
az ml compute list-usage --resource-group <rg> --workspace-name <ws>
```
You're looking for `Standard NCADS A100 v4 Family` showing non-zero limit.

## Environment variables (`.env`)
```bash
# AzureML
AZURE_SUBSCRIPTION_ID=<your-subscription-id>
AZURE_RESOURCE_GROUP=<your-resource-group>
AZUREML_WORKSPACE_NAME=<your-azureml-workspace>
AZUREML_COMPUTE_NAME=a100-cluster-1node            # matches Bicep output
AZURE_REGION=eastus2
AZURE_AUTH_MODE=vscode                            # or device_code/service_principal
AZURE_CLIENT_ID=                                   # service_principal only
AZURE_CLIENT_SECRET=<service-principal-secret>     # service_principal only

# Foundry navigation labels from ../MSFT Non Prod.txt. These are Foundry resources, not the AzureML workspace.
AZURE_AI_FOUNDRY_HUB_NAME=maf-finetuning-poc-jp-001
AZURE_AI_FOUNDRY_PROJECT_NAME=proj-finetuning-poc-001

# Hugging Face — token used by the training job to pull gated Gemma weights
HF_TOKEN=<hugging-face-read-token>
HF_MODEL_ID=google/gemma-4-E4B-it

# Training hyperparameters (override as needed)
LORA_RANK=16
LORA_ALPHA=32
LEARNING_RATE=2e-4
NUM_EPOCHS=3
PER_DEVICE_BATCH_SIZE=4
GRAD_ACCUM_STEPS=4

# Endpoint name (must be globally unique within region, lowercase, alphanumeric+hyphens)
ENDPOINT_NAME=gemma4-eim-demo
DEPLOYMENT_NAME=blue
```

You can start from `.env.example` and fill in `HF_TOKEN`. Keep `.env` local; do not commit tokens.

## One-time: store HF token in Key Vault
Best practice — don't pass `HF_TOKEN` as a literal env in the job. Stash it in the workspace's Key Vault and reference it from the job.

```bash
# The AzureML workspace creates an associated Key Vault. Find it:
KV_NAME=$(az ml workspace show -n $AZUREML_WORKSPACE_NAME -g $AZURE_RESOURCE_GROUP --query key_vault -o tsv | sed 's|.*/||')

# Put the HF token in
az keyvault secret set --vault-name $KV_NAME --name HF-TOKEN --value $HF_TOKEN
```

The training job's environment can then resolve this at runtime via managed identity. The submit script (`src/03_submit_training_job.py`) wires this up via an `environment_variables` block that references the Key Vault.

## Install control-plane dependencies (your laptop, not the GPU node)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell, use:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run the split-screen demo app

```bash
streamlit run demo_app/app.py
```

The Streamlit sidebar can create/update the single A100-backed endpoint and delete it after the demo. Deleting the endpoint is the billing stop button; the AML compute cluster still auto-scales to 0 for training.

## Sanity check
```bash
python -c "from azure.ai.ml import MLClient; from azure.identity import DefaultAzureCredential; \
import os; ml = MLClient(DefaultAzureCredential(), os.environ['AZURE_SUBSCRIPTION_ID'], \
os.environ['AZURE_RESOURCE_GROUP'], os.environ['AZUREML_WORKSPACE_NAME']); \
print('Workspace OK:', ml.workspace_name); \
print('Compute OK:', ml.compute.get(os.environ['AZUREML_COMPUTE_NAME']).provisioning_state)"
```

Should print `Workspace OK: <name>` and `Compute OK: Succeeded`. If compute shows `Creating` wait a minute and re-run.

## Notes on Gemma gated access
Per HuggingFace, `google/gemma-4-E4B-it` requires:
1. A HuggingFace account
2. Acceptance of the Gemma license terms on the model page
3. A user access token with read scope

Without all three, the training job will fail at the `from_pretrained()` call with a 401. The Foundry HF integration handles this for *inference* via gated model access, but for fine-tuning we pull weights directly inside the training job, so the token must be available in the job's environment.
