"""
src/05_eval.py
==============
Compare base Gemma 4B vs LoRA-tuned Gemma 4B on the same eval prompts.

The live demo uses one A100-backed AzureML endpoint. The scoring script loads
base Gemma 4B and the LoRA adapter once, then toggles adapter usage per request:
    - use_adapter=false : base Gemma 4B behavior
    - use_adapter=true  : fine-tuned Gemma 4B behavior

Run:
    python src/05_eval.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from rich import print as rprint
from rich.panel import Panel
from rich.table import Table

from demo_runtime import SYSTEM_PROMPT, call_endpoint, refresh_endpoint_info

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / ".job_state.json"
WINNER_EVAL_FILE = REPO_ROOT / "data" / "winner_eval.json"

EVAL_PROMPTS: list[dict[str, Any]] = [
    {
        "name": "lookup-member",
        "user": (
            "DOM:\n<form id='member-lookup'>\n"
            "  <input id='member-id' />\n  <button id='search-btn'>Search</button>\n</form>"
            "\n\nInstruction: Look up member M10000042"
        ),
        "expected_selectors": {"#member-id", "#search-btn"},
        "gold": {
            "actions": [
                {"type": "type", "selector": "#member-id", "value": "M10000042"},
                {"type": "click", "selector": "#search-btn"},
            ]
        },
    },
    {
        "name": "extract-claim-status",
        "user": (
            "DOM:\n<div class='claim-detail'>\n"
            "  <span class='claim-id'>CLM-2026-100200</span>\n"
            "  <span class='status' data-status='paid'>Paid</span>\n"
            "  <span class='paid-amount'>$1842.50</span>\n"
            "</div>"
            "\n\nInstruction: Extract the status and paid amount for claim CLM-2026-100200"
        ),
        "expected_selectors": {".claim-detail .status", ".claim-detail .paid-amount"},
        "gold": {
            "actions": [
                {"type": "extract", "selector": ".claim-detail .status", "as": "status"},
                {"type": "extract", "selector": ".claim-detail .paid-amount", "as": "paid_amount"},
            ]
        },
    },
    {
        "name": "submit-prior-auth",
        "user": (
            "DOM:\n<form id='pa-request'>\n"
            "  <input id='pa-member' />\n  <input id='pa-provider-npi' />\n"
            "  <input id='pa-cpt' />\n  <input id='pa-diagnosis' />\n"
            "  <button id='pa-submit'>Submit Authorization</button>\n</form>"
            "\n\nInstruction: Submit a prior authorization for member M10000007, "
            "provider NPI 1000000023, procedure 70551, diagnosis M54.5"
        ),
        "expected_selectors": {"#pa-member", "#pa-provider-npi", "#pa-cpt", "#pa-diagnosis", "#pa-submit"},
        "gold": None,
    },
]


@dataclass
class Score:
    valid_json: bool = False
    schema_ok: bool = False
    selector_valid: bool = False
    selector_policy_hit: bool = False
    no_missing_actions: bool = False
    step_order_ok: bool = False
    exact_match: bool = False

    @property
    def passed(self) -> int:
        return sum([
            self.valid_json,
            self.schema_ok,
            self.selector_valid,
            self.selector_policy_hit,
            self.no_missing_actions,
            self.step_order_ok,
            self.exact_match,
        ])


def load_eval_prompts() -> list[dict[str, Any]]:
    if WINNER_EVAL_FILE.exists():
        return json.loads(WINNER_EVAL_FILE.read_text(encoding="utf-8"))
    return EVAL_PROMPTS


def looks_like_css_selector(selector: Any) -> bool:
    if not isinstance(selector, str) or not selector.strip():
        return False
    stripped = selector.strip()
    return stripped.startswith(("#", ".", "[")) or "#" in stripped or "[" in stripped


def score_response(raw: str, prompt: dict) -> Score:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        if len(parts) >= 2:
            body = parts[1]
            if body.startswith("json"):
                body = body[4:]
            cleaned = body.strip()

    s = Score()
    try:
        parsed = json.loads(cleaned)
        s.valid_json = True
    except json.JSONDecodeError:
        return s

    s.schema_ok = (
        isinstance(parsed, dict)
        and "actions" in parsed
        and isinstance(parsed["actions"], list)
        and all(isinstance(a, dict) and "type" in a and "selector" in a for a in parsed["actions"])
    )
    actions = parsed.get("actions", []) if isinstance(parsed, dict) else []
    used = {a.get("selector") for a in actions if isinstance(a, dict)}
    expected_selectors = set(prompt.get("expected_selectors", []))
    expected_types = prompt.get("expected_action_types")
    gold_actions = prompt.get("gold", {}).get("actions", []) if prompt.get("gold") else []
    s.selector_valid = s.schema_ok and all(looks_like_css_selector(a.get("selector")) for a in actions)
    s.selector_policy_hit = bool(expected_selectors) and expected_selectors.issubset(used)
    s.no_missing_actions = bool(gold_actions) and len(actions) >= len(gold_actions)
    if expected_types:
        actual_types = [a.get("type") for a in actions if isinstance(a, dict)]
        s.step_order_ok = actual_types[: len(expected_types)] == expected_types
    if prompt.get("gold") is not None:
        s.exact_match = parsed == prompt["gold"]
    return s


def main() -> None:
    load_dotenv()

    rprint(Panel.fit("[bold]Step 05 — Evaluation: base vs LoRA-tuned Gemma 4B[/bold]"))

    if not STATE_FILE.exists():
        rprint("[red].job_state.json not found.[/red]")
        sys.exit(1)
    state = json.loads(STATE_FILE.read_text())

    if "scoring_uri" not in state:
        rprint("[red]No scoring_uri in state. Did step 04 complete?[/red]")
        sys.exit(1)

    endpoint_info = refresh_endpoint_info()

    rprint(f"  endpoint:    [cyan]{state['endpoint_name']}[/cyan]")
    rprint("  baseline:    same endpoint with LoRA adapter disabled")
    rprint("  fine-tuned:  same endpoint with LoRA adapter enabled\n")

    eval_prompts = load_eval_prompts()
    table = Table(title="Base vs LoRA-tuned Gemma 4B winner eval (higher = better, max 7/7)")
    table.add_column("Eval prompt", style="cyan", no_wrap=True)
    table.add_column("Base", justify="center")
    table.add_column("LoRA-tuned", justify="center")
    table.add_column("Delta", justify="center", style="green")

    detailed = []
    base_total = ft_total = 0
    for p in eval_prompts:
        rprint(f"  evaluating [cyan]{p['name']}[/cyan]...")
        msgs = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": p["user"]},
        ]
        base_raw = call_endpoint(msgs, use_adapter=False, max_new_tokens=160, endpoint_info=endpoint_info)
        base_score = score_response(base_raw, p)
        base_total += base_score.passed

        ft_raw = call_endpoint(msgs, use_adapter=True, max_new_tokens=160, endpoint_info=endpoint_info)
        ft_score = score_response(ft_raw, p)
        ft_total += ft_score.passed

        row = [p["name"]]
        delta = ft_score.passed - base_score.passed
        row.extend([f"{base_score.passed}/7", f"{ft_score.passed}/7", f"+{delta}" if delta > 0 else str(delta)])
        detailed.append({
            "name": p["name"],
            "base_response": base_raw,
            "ft_response": ft_raw,
            "base_score": base_score.__dict__,
            "ft_score": ft_score.__dict__,
        })

        table.add_row(*row)

    rprint(table)
    rprint(
        f"\n[bold]Total:[/bold]  base={base_total}/{7*len(eval_prompts)}   "
        f"LoRA-tuned={ft_total}/{7*len(eval_prompts)}   "
        f"[green]Delta=+{ft_total - base_total}[/green]"
    )

    out = REPO_ROOT / "results.json"
    out.write_text(json.dumps(detailed, indent=2))
    rprint(f"\n[dim]Detailed responses written to {out.relative_to(REPO_ROOT)}[/dim]")


if __name__ == "__main__":
    main()
