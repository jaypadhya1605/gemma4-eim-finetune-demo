"""
data/generate_synthetic_data.py
================================
Deterministic, synthetic, PHI-free dataset of computer-use / navigation /
extraction tasks for fine-tuning Gemma 4B via LoRA SFT.

Output format: OpenAI-style messages JSONL with system/user/assistant turns.
The training script applies Gemma 4's chat template via tokenizer.apply_chat_template.

Governance:
- 100% synthetic. Random IDs from fixed dictionaries.
- No Lix, no Lex, no real Molina data.
- Reproducible — fixed seed.

Output:
- data/synthetic_train.jsonl  (default: 100 records)
- data/synthetic_validation.jsonl  (default: 20 records)

Usage:
    python data/generate_synthetic_data.py
    python data/generate_synthetic_data.py --train 500 --val 50 --seed 7
"""
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

# -- Synthetic vocabulary (all fake, no real PHI/PII) ------------------------
FAKE_MEMBER_IDS = [f"M{n:08d}" for n in range(10_000_000, 10_000_050)]
FAKE_CLAIM_IDS = [f"CLM-2026-{n:06d}" for n in range(100_000, 100_050)]
FAKE_NPI_IDS = [f"{n:010d}" for n in range(1_000_000_000, 1_000_000_050)]
FAKE_AUTH_IDS = [f"PA-{n:07d}" for n in range(2_000_000, 2_000_050)]
FAKE_ICD_CODES = ["E11.9", "I10", "J45.909", "M54.5", "K21.9", "F32.9", "N39.0"]
FAKE_CPT_CODES = ["99213", "99214", "70551", "73721", "80053", "85025", "93000"]


def task_lookup_member(rng: random.Random) -> tuple[str, str]:
    member_id = rng.choice(FAKE_MEMBER_IDS)
    dom = (
        "<form id='member-lookup'>\n"
        "  <input id='member-id' placeholder='Member ID' />\n"
        "  <button id='search-btn'>Search</button>\n"
        "</form>"
    )
    actions = {"actions": [
        {"type": "type", "selector": "#member-id", "value": member_id},
        {"type": "click", "selector": "#search-btn"},
    ]}
    return f"DOM:\n{dom}\n\nInstruction: Look up member {member_id}", json.dumps(actions, separators=(",", ":"))


def task_submit_prior_auth(rng: random.Random) -> tuple[str, str]:
    member_id = rng.choice(FAKE_MEMBER_IDS)
    npi = rng.choice(FAKE_NPI_IDS)
    cpt = rng.choice(FAKE_CPT_CODES)
    icd = rng.choice(FAKE_ICD_CODES)
    dom = (
        "<form id='pa-request'>\n"
        "  <input id='pa-member' />\n"
        "  <input id='pa-provider-npi' />\n"
        "  <input id='pa-cpt' />\n"
        "  <input id='pa-diagnosis' />\n"
        "  <button id='pa-submit'>Submit Authorization</button>\n"
        "</form>"
    )
    instruction = (
        f"Submit a prior authorization for member {member_id}, provider NPI "
        f"{npi}, procedure {cpt}, diagnosis {icd}"
    )
    actions = {"actions": [
        {"type": "type", "selector": "#pa-member", "value": member_id},
        {"type": "type", "selector": "#pa-provider-npi", "value": npi},
        {"type": "type", "selector": "#pa-cpt", "value": cpt},
        {"type": "type", "selector": "#pa-diagnosis", "value": icd},
        {"type": "click", "selector": "#pa-submit"},
    ]}
    return f"DOM:\n{dom}\n\nInstruction: {instruction}", json.dumps(actions, separators=(",", ":"))


def task_extract_claim_status(rng: random.Random) -> tuple[str, str]:
    claim_id = rng.choice(FAKE_CLAIM_IDS)
    status = rng.choice(["Paid", "Denied", "Pending", "In Review"])
    paid_amount = round(rng.uniform(50.00, 4500.00), 2)
    dom = (
        f"<div class='claim-detail'>\n"
        f"  <span class='claim-id'>{claim_id}</span>\n"
        f"  <span class='status' data-status='{status.lower()}'>{status}</span>\n"
        f"  <span class='paid-amount'>${paid_amount}</span>\n"
        f"</div>"
    )
    actions = {"actions": [
        {"type": "extract", "selector": ".claim-detail .status", "as": "status"},
        {"type": "extract", "selector": ".claim-detail .paid-amount", "as": "paid_amount"},
    ]}
    instruction = f"Extract the status and paid amount for claim {claim_id}"
    return f"DOM:\n{dom}\n\nInstruction: {instruction}", json.dumps(actions, separators=(",", ":"))


def task_check_auth_status(rng: random.Random) -> tuple[str, str]:
    auth_id = rng.choice(FAKE_AUTH_IDS)
    dom = (
        "<form id='auth-status'>\n"
        "  <input id='auth-number' placeholder='Authorization Number' />\n"
        "  <button id='check-status'>Check Status</button>\n"
        "</form>"
    )
    actions = {"actions": [
        {"type": "type", "selector": "#auth-number", "value": auth_id},
        {"type": "click", "selector": "#check-status"},
    ]}
    return f"DOM:\n{dom}\n\nInstruction: Check status of authorization {auth_id}", json.dumps(actions, separators=(",", ":"))


def task_navigate_to_eligibility(rng: random.Random) -> tuple[str, str]:
    member_id = rng.choice(FAKE_MEMBER_IDS)
    dom = (
        "<nav>\n"
        "  <a id='nav-claims' href='#claims'>Claims</a>\n"
        "  <a id='nav-eligibility' href='#eligibility'>Eligibility</a>\n"
        "  <a id='nav-auth' href='#auth'>Authorizations</a>\n"
        "</nav>\n"
        "<form id='elig-form'>\n"
        "  <input id='elig-member' />\n"
        "  <button id='elig-check'>Verify</button>\n"
        "</form>"
    )
    actions = {"actions": [
        {"type": "click", "selector": "#nav-eligibility"},
        {"type": "type", "selector": "#elig-member", "value": member_id},
        {"type": "click", "selector": "#elig-check"},
    ]}
    instruction = f"Go to eligibility and verify member {member_id}"
    return f"DOM:\n{dom}\n\nInstruction: {instruction}", json.dumps(actions, separators=(",", ":"))


TASKS: list[Callable[[random.Random], tuple[str, str]]] = [
    task_lookup_member,
    task_submit_prior_auth,
    task_extract_claim_status,
    task_check_auth_status,
    task_navigate_to_eligibility,
]


def make_record(rng: random.Random) -> dict:
    user_content, assistant_content = rng.choice(TASKS)(rng)
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ]
    }


def write_jsonl(path: Path, n: int, rng: random.Random) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for _ in range(n):
            f.write(json.dumps(make_record(rng), ensure_ascii=False) + "\n")
    print(f"  wrote {n} records → {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=int, default=100)
    parser.add_argument("--val", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()

    train_rng = random.Random(args.seed)
    val_rng = random.Random(args.seed + 1)

    print(f"Generating synthetic dataset (seed={args.seed})...")
    write_jsonl(args.out / "synthetic_train.jsonl", args.train, train_rng)
    write_jsonl(args.out / "synthetic_validation.jsonl", args.val, val_rng)
    print("Done. All data is synthetic. No PHI / no Molina data used.")


if __name__ == "__main__":
    main()
