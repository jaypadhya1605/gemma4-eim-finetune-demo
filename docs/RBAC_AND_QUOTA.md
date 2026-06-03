# RBAC + Quota Checklist

> **Use this** when you're scoping the demo with Chirag — these are the prerequisites on his side (or on whichever subscription hosts the demo).

## 1. Compute quota

Required: **at least 24 vCPUs of `Standard NCADS A100 v4 Family`** in the target region.

This is one node of `Standard_NC24ads_A100_v4` (1× A100 80GB, 24 vCPUs).

Check with:
```bash
az ml compute list-usage \
  --resource-group <rg> \
  --workspace-name <ws> \
  --query "[?contains(name.localizedValue, 'NCADS A100 v4')]" \
  --output table
```

If quota = 0: file a quota request via Azure portal → Subscription → Usage + quotas → Request increase. Typical turnaround is 1–3 business days for standard requests, longer for ND-series.

**Alternative SKUs if A100 isn't available:**
- `Standard_NC40ads_H100_v5` (1× H100 80GB) — newer, faster, may have quota
- `Standard_ND96isr_H100_v5` (8× H100) — overkill but works
- Avoid: `Standard_NC*_T4_*`, `Standard_NC*_V100_*` — too small or too slow for 4B-class models

## 2. RBAC roles

| Role | Scope | Who | Used for |
|---|---|---|---|
| `Contributor` | Resource group (one-time) | Jay (or whoever runs Bicep) | Deploying `infra/main.bicep` |
| `AzureML Data Scientist` | Workspace | Jay | Submitting training jobs, registering models |
| `AzureML Compute Operator` | Workspace | Jay | Creating/managing online endpoints |
| `Key Vault Secrets Officer` | Workspace's Key Vault | Jay | Writing HF_TOKEN secret |
| `Reader` | Workspace | Chirag (optional) | Observing job runs, eval results |

The Bicep template auto-assigns the first three to the `principalId` you pass in. Other principals (e.g., Chirag's account if he wants read access) need to be added separately:

```bash
az role assignment create \
  --assignee <chirag-objid> \
  --role "Reader" \
  --scope "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.MachineLearningServices/workspaces/<ws>"
```

## 3. Hugging Face prerequisites

| Step | Notes |
|---|---|
| Create HF account | Free, https://huggingface.co/join |
| Accept Gemma 4 license | Go to `https://huggingface.co/google/gemma-4-E4B-it`, click "Agree and access repository" |
| Generate token | Settings → Access Tokens → New token (Read scope is sufficient) |
| Store in Key Vault | `az keyvault secret set --vault-name <kv> --name HF-TOKEN --value <token>` |

## 4. Network requirements

If the demo runs from inside a Molina-controlled network:
- HTTPS to `*.azure.com`, `*.azureml.net`, `*.azureml.ms` (AzureML control plane)
- HTTPS to `*.blob.core.windows.net` (artifact storage)
- HTTPS to `huggingface.co` and `cdn-lfs.huggingface.co` (gated model download into the AzureML job)
- HTTPS to `pypi.org` and `files.pythonhosted.org` (pip install in the training environment)

If outbound HF access is blocked, the alternative is to **pre-download Gemma 4 weights** into the workspace's blob storage as a Data asset, then mount it into the job. The training script can be modified to take a `--model_local_path` instead of `--model_id`. Mention this to Chirag — likely needed for any real production rollout.

## 5. Pre-flight checks (run these before the demo)

```bash
# A. Confirm you can hit the workspace
az ml workspace show -n $AZUREML_WORKSPACE_NAME -g $AZURE_RESOURCE_GROUP

# B. Confirm the A100 compute exists and is reachable
az ml compute show -n a100-cluster-1node -w $AZUREML_WORKSPACE_NAME -g $AZURE_RESOURCE_GROUP

# C. Confirm HF token works
python -c "from huggingface_hub import HfApi; \
  api = HfApi(token='$HF_TOKEN'); \
  print(api.whoami())"

# D. Confirm Gemma access (this will 401 if license not accepted)
python -c "from huggingface_hub import hf_hub_download; \
  hf_hub_download(repo_id='google/gemma-4-E4B-it', filename='config.json', token='$HF_TOKEN')"
```

If all four pass, you're clear to run `02_prepare_data.py` → `03_submit_training_job.py`.
