# 00 — Demo Script (Gemma 4B Fine-Tune, Live Walkthrough)

> **Audience:** Chirag, Dhanshri, EIM team  
> **Length:** 5–7 minutes plus Q&A  
> **Goal:** Show Gemma 4B fine-tuned end-to-end on Chirag's A100s, with measurable before/after on computer-use tasks.

---

## Beat 1 — Frame (≈20 sec)
> "Last call you asked: can we fine-tune Gemma 4B for computer-use tasks with synthetic data, using the A100 quota you already have. I went and built it. What you're about to see runs on AzureML managed compute against `google/gemma-4-E4B-it` — the Effective 4B instruction-tuned variant from the Gemma 4 family that dropped April 2nd."

## Beat 2 — Why LoRA (≈20 sec)
> "I'm using LoRA adapters, not full fine-tuning. Two reasons. One, it fits on a single A100 80GB with room to spare — full FT would need multi-GPU or DeepSpeed. Two, this is how teams actually ship task-specific fine-tunes in production: the base Gemma weights stay frozen, you train a tiny adapter — about 0.1% of the parameter count — and you can swap adapters per use case without redeploying the base model. Pattern matches what you'd want for distinct EIM workflows."

## Beat 3 — Data discipline (≈15 sec)
> "Data is 100% synthetic. Deterministic generator, fixed seed, fake member IDs, fake claim numbers, no Lix, no Lex. The task shape is what matters: given a DOM snippet and an instruction, output the next click or extract action as JSON. Healthcare-flavored selectors only."

## Beat 4 — Live walkthrough (≈3 min)

**[Show `data/synthetic_train.jsonl`]**
> "100 training records, 20 validation records. Each one is a system/user/assistant turn. The training script applies Gemma's chat template when it tokenizes."

**[Show `src/03_submit_training_job.py` running, or the AzureML Studio jobs view]**
> "The control-plane code is small — about 60 lines of `azure-ai-ml` SDK. It picks up our training script, mounts the data asset, points at the A100 cluster, and submits. The real work happens in `training/train.py` on the GPU node."

**[Show `training/train.py` briefly]**
> "Three blocks. Load Gemma 4 with bf16 on the GPU. Wrap it in a LoRA config — rank 16, alpha 32, targeting attention and MLP projections. Then TRL's `SFTTrainer` does the rest. The whole training script is under 200 lines."

**[Show training logs in AzureML Studio — loss curve dropping]**
> "Loss drops cleanly. On 100 examples this converges in about 30 minutes on one A100. At the end, the adapter — a few hundred MB — lands back in AzureML's outputs."

**[Show `src/04_register_and_deploy.py` completing]**
> "Adapter gets registered as an AzureML model artifact. Then deployed to a managed online endpoint that loads the base Gemma weights plus the adapter at boot."

**[Show `streamlit run demo_app/app.py`]**
> "This is the customer-facing view. Left side is base Gemma 4B with the adapter disabled. Right side is the same endpoint with the LoRA adapter enabled. One A100 endpoint, two behaviors. That keeps the comparison clean without doubling hosting cost."

**[Send a prior-auth or claim-extraction prompt]**
> "Base Gemma tends to explain or wrap the answer. The tuned model has learned the Molina EIM contract: no prose, no markdown fences, just the JSON action plan with the right selectors. That is the value of fine-tuning here."

## Beat 5 — Cost framing (≈30 sec)
> "On cost: training was about an hour on one A100, so single-digit dollars. The bigger lever is inference. The demo deliberately uses one endpoint that can run both base and tuned variants. The A100 bills hourly while that endpoint exists, so the Streamlit sidebar has a delete button. I use that immediately after the demo to stop billing."

## Beat 6 — What's next (≈30 sec)
> "Three follow-ups for you:
> 1. Pick the actual production flow we're targeting. Today's data is generic computer-use. Real value comes from synthetic data that mirrors your specific high-volume flow.
> 2. Confirm graders. If we move past SFT into DPO or reinforcement learning later, the graders are the hardest part — Dhanshri called this out on April 29. Worth scoping early.
> 3. Endpoint home. We can keep this in AzureML, or expose it through Foundry as a managed online endpoint reference. Your call."

---

## Backup Q&A

**Q: Why E4B and not the 31B?**  
A: 31B doesn't fit on a single A100 80GB for training without sharding. E4B fits comfortably, trains fast, deploys cheap, and matches Chirag's stated criteria — small, open-source, latest. If we later need more capacity, we move to the 26B-A4B MoE variant which inferences at 4B speed but has 26B of knowledge.

**Q: Why LoRA rank 16?**  
A: Sweet spot for instruction-tuning at this scale. Rank 8 sometimes under-fits structured-output tasks. Rank 32+ doesn't add measurable lift on small datasets and costs more memory. We can ablate this if you want.

**Q: What about quantization — QLoRA?**  
A: Not needed on A100 80GB for a 4B model. QLoRA matters when you're trying to fit 70B on a 24GB consumer GPU. On A100, bf16 is the cleaner choice — no quantization error, faster matmul.

**Q: Can we serve the merged model instead of adapter-at-inference?**  
A: Yes. The deploy script supports a `--merge` flag that merges LoRA weights into base before pushing to the endpoint. Tradeoff: merged model can't be swapped at runtime; un-merged supports multi-adapter serving via vLLM or similar.

**Q: How does this come back into Foundry?**  
A: The AzureML managed online endpoint is callable from any Foundry-side workflow. Or we can register the merged model in the Foundry catalog as a custom model. Path depends on whether you want this discoverable to other EIM teams or kept project-scoped.

**Q: Production hardening?**  
A: Private endpoint on the workspace, customer-managed keys on the storage account, Application Insights for endpoint telemetry, managed identity for HF token rotation, and a CI pipeline that re-runs SFT on new synthetic data and gates promotion on the eval suite passing. Happy to scope a hardening doc.
