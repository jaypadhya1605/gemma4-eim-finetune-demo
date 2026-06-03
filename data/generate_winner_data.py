"""Generate hard synthetic examples for a visible fine-tuning win."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Callable

SYSTEM_PROMPT = (
    "You are a computer-use agent for a healthcare web application. "
    "Given a DOM snippet and a natural-language instruction, output the next "
    "actions as a JSON object with a top-level 'actions' array. Each action "
    "is either {\"type\":\"type\",\"selector\":\"...\",\"value\":\"...\"} "
    "or {\"type\":\"click\",\"selector\":\"...\"} or "
    "{\"type\":\"extract\",\"selector\":\"...\",\"as\":\"<field_name>\"}. "
    "Return only the JSON object, no prose, no markdown fences."
)

MEMBERS = [f"M{n:08d}" for n in range(10_000_040, 10_000_180)]
AUTHS = [f"PA-{n:07d}" for n in range(2_000_030, 2_000_170)]
CLAIMS = [f"CLM-2026-{n:06d}" for n in range(100_150, 100_290)]
NPIS = [f"{n:010d}" for n in range(1_000_000_070, 1_000_000_210)]
CPTS = ["99213", "99214", "70551", "73721", "80053", "85025", "93000"]
ICDS = ["E11.9", "I10", "J45.909", "M54.5", "K21.9", "F32.9", "N39.0"]


def sel(kind: str, name: str) -> str:
    return f"[data-eim-{kind}='{name}']"


def make_record(name: str, user: str, actions: list[dict[str, str]]) -> dict:
    return {
        "name": name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps({"actions": actions}, separators=(",", ":"))},
        ],
    }


def auth_nurse_review(rng: random.Random) -> dict:
    member = rng.choice(MEMBERS)
    auth = rng.choice(AUTHS)
    noise = rng.randint(1000, 9999)
    user = f"""DOM:
<nav>
  <button id='nav-{noise}-mbr' data-eim-action='open-member-center'>Members</button>
  <button id='nav-{noise}-auth' data-eim-action='open-authorizations'>Authorizations</button>
  <button id='nav-{noise}-claims' data-eim-action='open-claims'>Claims</button>
</nav>
<section id='auth-workqueue-{noise}' data-workflow='auth-nurse-review'>
  <input id='member-search-{noise}' aria-label='Subscriber or Member' data-eim-field='member-id' />
  <input id='auth-id-{noise}' aria-label='Authorization Number' data-eim-field='authorization-id' />
  <button id='open-auth-{noise}' data-eim-action='load-auth-case'>Load Case</button>
  <button id='submit-review-{noise}' data-eim-action='complete-nurse-review'>Complete Nurse Review</button>
</section>

Instruction: Open Molina authorization case {auth} for member {member} and complete nurse review"""
    return make_record("auth-nurse-review", user, [
        {"type": "click", "selector": sel("action", "open-authorizations")},
        {"type": "type", "selector": sel("field", "member-id"), "value": member},
        {"type": "type", "selector": sel("field", "authorization-id"), "value": auth},
        {"type": "click", "selector": sel("action", "load-auth-case")},
        {"type": "click", "selector": sel("action", "complete-nurse-review")},
    ])


def prior_auth_policy_check(rng: random.Random) -> dict:
    member = rng.choice(MEMBERS)
    npi = rng.choice(NPIS)
    cpt = rng.choice(CPTS)
    icd = rng.choice(ICDS)
    noise = rng.randint(1000, 9999)
    user = f"""DOM:
<div class='workspace'>
  <a id='link-{noise}-auth' data-eim-action='open-authorizations'>Auth Center</a>
  <a id='link-{noise}-claim' data-eim-action='open-claims'>Claim Center</a>
</div>
<form id='pa-create-{noise}' data-workflow='prior-auth-policy-check'>
  <input id='mbr-{noise}' data-eim-field='member-id' />
  <input id='provider-{noise}' data-eim-field='provider-npi' />
  <input id='procedure-{noise}' data-eim-field='procedure-code' />
  <input id='dx-{noise}' data-eim-field='diagnosis-code' />
  <button id='policy-{noise}' data-eim-action='run-policy-check'>Run Policy Check</button>
  <button id='submit-{noise}' data-eim-action='submit-authorization'>Submit Authorization</button>
</form>

Instruction: Create a Molina prior authorization for member {member}, provider {npi}, CPT {cpt}, diagnosis {icd}; run policy check before submitting"""
    return make_record("prior-auth-policy-check", user, [
        {"type": "click", "selector": sel("action", "open-authorizations")},
        {"type": "type", "selector": sel("field", "member-id"), "value": member},
        {"type": "type", "selector": sel("field", "provider-npi"), "value": npi},
        {"type": "type", "selector": sel("field", "procedure-code"), "value": cpt},
        {"type": "type", "selector": sel("field", "diagnosis-code"), "value": icd},
        {"type": "click", "selector": sel("action", "run-policy-check")},
        {"type": "click", "selector": sel("action", "submit-authorization")},
    ])


def claim_denial_packet(rng: random.Random) -> dict:
    claim = rng.choice(CLAIMS)
    member = rng.choice(MEMBERS)
    noise = rng.randint(1000, 9999)
    user = f"""DOM:
<nav>
  <button id='claim-nav-{noise}' data-eim-action='open-claims'>Claims</button>
  <button id='auth-nav-{noise}' data-eim-action='open-authorizations'>Authorizations</button>
</nav>
<section id='claim-review-{noise}' data-workflow='denial-packet'>
  <input id='claim-field-{noise}' data-eim-field='claim-id' />
  <input id='member-field-{noise}' data-eim-field='member-id' />
  <button id='load-claim-{noise}' data-eim-action='load-claim'>Load Claim</button>
  <span class='status-pill' data-eim-value='claim-status'>Denied</span>
  <span class='reason' data-eim-value='denial-reason'>Missing prior authorization</span>
  <button id='packet-{noise}' data-eim-action='create-denial-packet'>Create Denial Packet</button>
</section>

Instruction: For member {member}, load denied claim {claim}, extract status and denial reason, then create the denial packet"""
    return make_record("claim-denial-packet", user, [
        {"type": "click", "selector": sel("action", "open-claims")},
        {"type": "type", "selector": sel("field", "member-id"), "value": member},
        {"type": "type", "selector": sel("field", "claim-id"), "value": claim},
        {"type": "click", "selector": sel("action", "load-claim")},
        {"type": "extract", "selector": sel("value", "claim-status"), "as": "claim_status"},
        {"type": "extract", "selector": sel("value", "denial-reason"), "as": "denial_reason"},
        {"type": "click", "selector": sel("action", "create-denial-packet")},
    ])


def eligibility_pcp_review(rng: random.Random) -> dict:
    member = rng.choice(MEMBERS)
    noise = rng.randint(1000, 9999)
    user = f"""DOM:
<nav>
  <a id='nav-elg-{noise}' data-eim-action='open-eligibility'>Eligibility</a>
  <a id='nav-auth-{noise}' data-eim-action='open-authorizations'>Authorizations</a>
</nav>
<section id='eligibility-{noise}' data-workflow='eligibility-pcp-review'>
  <input id='subscriber-{noise}' data-eim-field='member-id' />
  <button id='verify-{noise}' data-eim-action='verify-eligibility'>Verify</button>
  <span id='plan-{noise}' data-eim-value='plan-status'>Active</span>
  <span id='pcp-{noise}' data-eim-value='pcp-name'>Avery Primary Care</span>
</section>

Instruction: Verify eligibility for member {member}, then extract plan status and PCP name"""
    return make_record("eligibility-pcp-review", user, [
        {"type": "click", "selector": sel("action", "open-eligibility")},
        {"type": "type", "selector": sel("field", "member-id"), "value": member},
        {"type": "click", "selector": sel("action", "verify-eligibility")},
        {"type": "extract", "selector": sel("value", "plan-status"), "as": "plan_status"},
        {"type": "extract", "selector": sel("value", "pcp-name"), "as": "pcp_name"},
    ])


TASKS: list[Callable[[random.Random], dict]] = [
    auth_nurse_review,
    prior_auth_policy_check,
    claim_denial_packet,
    eligibility_pcp_review,
]


def build_records(count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    return [TASKS[index % len(TASKS)](rng) for index in range(count)]


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in records:
            f.write(json.dumps({"messages": item["messages"]}, ensure_ascii=False) + "\n")
    print(f"  wrote {len(records)} records -> {path}")


def write_eval(path: Path, records: list[dict]) -> None:
    prompts = []
    for item in records:
        gold = json.loads(item["messages"][-1]["content"])
        prompts.append({
            "name": item["name"],
            "user": item["messages"][1]["content"],
            "gold": gold,
            "expected_selectors": [action["selector"] for action in gold["actions"]],
            "expected_action_types": [action["type"] for action in gold["actions"]],
        })
    path.write_text(json.dumps(prompts, indent=2), encoding="utf-8")
    print(f"  wrote {len(prompts)} eval prompts -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=int, default=96)
    parser.add_argument("--val", type=int, default=24)
    parser.add_argument("--eval", type=int, default=16)
    parser.add_argument("--seed", type=int, default=410)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()

    print(f"Generating hard winner dataset (seed={args.seed})...")
    write_jsonl(args.out / "synthetic_train.jsonl", build_records(args.train, args.seed))
    write_jsonl(args.out / "synthetic_validation.jsonl", build_records(args.val, args.seed + 1_000))
    write_eval(args.out / "winner_eval.json", build_records(args.eval, args.seed + 2_000))
    print("Done. All examples are synthetic and PHI-free.")


if __name__ == "__main__":
    main()