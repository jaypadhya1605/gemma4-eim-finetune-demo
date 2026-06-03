# Results Pack — Base Gemma 4B vs LoRA-Tuned Gemma 4B

> Fill this in after running `python src/05_eval.py`. Hand to Chirag/Dhanshri as the take-home artifact.

**Demo run:** `<YYYY-MM-DD>`  
**Base model:** `google/gemma-4-E4B-it` (Gemma 4, Effective 4B, instruction-tuned)  
**Adapter:** `gemma4-eim-lora-adapter:1` (LoRA r=16, α=32)  
**Training compute:** `Standard_NC24ads_A100_v4` (1× A100 80GB)  
**Training dataset:** 100 synthetic computer-use / extraction examples  
**Validation dataset:** 20 synthetic examples  
**Training duration:** `<wall-clock minutes>`  
**Trainable params:** `<from metadata.json>` / `<total>` (~0.1%)  
**Final train loss:** `<X.XX>`  
**Final eval loss:** `<X.XX>`  

---

## Headline numbers

| Metric | Base Gemma 4B | LoRA-tuned | Δ |
|---|---|---|---|
| Total eval score | `<x/12>` | `<y/12>` | `+<y-x>` |
| Valid JSON rate | `<x/3>` | `<y/3>` | `+<y-x>` |
| Schema-conformant rate | `<x/3>` | `<y/3>` | `+<y-x>` |
| Selector accuracy | `<x/3>` | `<y/3>` | `+<y-x>` |
| Exact-match rate | `<x/2>` | `<y/2>` | `+<y-x>` |

## Latency snapshot (1× A100 endpoint, single-stream)
| Model | Median tokens/sec | p50 latency (300-token completion) | p95 latency |
|---|---|---|---|
| Base Gemma 4B | `<x>` | `<x.xs>` | `<x.xs>` |
| LoRA-tuned | `<y>` | `<y.ys>` | `<y.ys>` |

LoRA adapters add negligible inference overhead (~1–3% in our experience) — the latency difference between rows above should be near-zero.

---

## Side-by-side: representative responses

### Example 1 — `lookup-member`
**Prompt:** Look up member M10000042 against a simple lookup form.

**Base Gemma 4B response:**
```
<paste base response from results.json>
```

**LoRA-tuned response:**
```
<paste ft response from results.json>
```

**Observation:** _Typical failure mode for base: wraps JSON in markdown fences, adds explanatory prose, or uses unquoted property names. LoRA-tuned should produce clean JSON exactly matching the training distribution._

---

### Example 2 — `extract-claim-status`
**Prompt:** Extract status + paid amount from claim detail HTML.

**Base Gemma 4B response:**
```
<paste>
```

**LoRA-tuned response:**
```
<paste>
```

**Observation:** _Base often pulls extra fields (claim_id, data-status attribute) that weren't requested. LoRA-tuned should respect the exact extraction list._

---

### Example 3 — `submit-prior-auth`
**Prompt:** 5-field prior authorization submission.

**Base Gemma 4B response:**
```
<paste>
```

**LoRA-tuned response:**
```
<paste>
```

**Observation:** _Longest sequence and the hardest. Base may reorder fields, skip fields, or output them as nested objects. LoRA-tuned should reproduce the canonical 5-action sequence._

---

## What this means

- **Reliability lift is the story.** Fine-tuning a small model on a narrow JSON schema is exactly the use case SFT excels at. Base Gemma 4B is a capable instruction-follower, but it's not constrained to your specific output contract until you train it to be.
- **Cost story works at scale.** A single A100 80GB can serve high-QPS structured-output inference. At meaningful traffic volume, fine-tuned Gemma 4B beats frontier-model per-call cost by a large multiple. Below ~10k calls/day, the hourly A100 hosting cost dominates and the savings disappear.
- **The pattern transfers.** Once you have the LoRA pipeline working, swapping the training data targets a new EIM workflow with minimal infra change.

## What this does NOT prove

- 100 training records is a demo dataset, not production. Production fine-tunes typically use thousands of examples and held-out test sets.
- Eval set of 3 prompts is for live demonstration. Production eval needs hundreds of prompts spanning the long tail of real production traffic.
- No claim about safety or hallucination here. If this model gets deployed in a real EIM workflow, an output-validation layer (JSON schema check + selector allow-list) is mandatory.

## Next steps

- [ ] Pick the actual production flow we're targeting and reshape synthetic data to mirror it.
- [ ] Build a larger eval set (hundreds of prompts) and a regression gate for any future adapter updates.
- [ ] Decide on serving topology: A100 endpoint per adapter, or multi-adapter vLLM serving across one endpoint.
- [ ] If we want this discoverable from Foundry: register the merged model in the Foundry catalog as a custom model.
