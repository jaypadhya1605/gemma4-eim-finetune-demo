from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from demo_runtime import (  # noqa: E402
    DEFAULT_ENDPOINT_NAME,
    DEMO_SCENARIOS,
    GEMMA_CATALOG_MODEL_ID,
    GEMMA_MODEL_ID,
    EndpointInfo,
    build_messages,
    call_endpoint,
    load_state,
    refresh_endpoint_info,
    run_step_script,
)

RESULTS_FILE = REPO_ROOT / "results.json"
WINNER_EVAL_FILE = REPO_ROOT / "data" / "winner_eval.json"

SCENARIO_COPY = {
    "auth-nurse-review": {
        "title": "Nurse Review: Open Authorization Case",
        "description": "A nurse opens the Authorizations workspace, loads a member authorization case, and completes the nurse review step.",
    },
    "prior-auth-policy-check": {
        "title": "Prior Auth: Run Policy Check Before Submit",
        "description": "A prior authorization request is created, the policy check is run first, and the authorization is submitted in the right order.",
    },
    "claim-denial-packet": {
        "title": "Claims: Create Denial Packet",
        "description": "A denied claim is opened, the status and denial reason are extracted, and a denial packet is created for follow-up.",
    },
    "eligibility-pcp-review": {
        "title": "Eligibility: Verify Member and Extract PCP",
        "description": "A member eligibility record is verified, then the active plan status and PCP name are extracted for review.",
    },
}


def load_winner_eval_by_prompt() -> dict[str, dict]:
    if not WINNER_EVAL_FILE.exists():
        return {}
    try:
        records = json.loads(WINNER_EVAL_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {record["user"]: record for record in records if "user" in record}


def scenario_key(scenario: dict) -> str:
    eval_name = scenario.get("eval_name")
    if eval_name:
        return str(eval_name)
    combined = f"{scenario.get('name', '')}\n{scenario.get('prompt', '')}".lower()
    for key in SCENARIO_COPY:
        if key in combined:
            return key
    return str(scenario.get("name", "scenario")).lower().replace(" ", "-")


def fallback_title(raw_name: str) -> str:
    cleaned = re.sub(r"^fine[- ]?tuned wins:\s*", "", raw_name, flags=re.IGNORECASE)
    return cleaned.strip().replace("-", " ").title()


def enrich_scenario_metadata(scenario: dict, prompt: str | None = None) -> dict:
    item = dict(scenario)
    eval_record = load_winner_eval_by_prompt().get(prompt or item.get("prompt", ""))
    if eval_record:
        item.setdefault("eval_name", eval_record.get("name"))
        item.setdefault("gold", eval_record.get("gold"))
        item.setdefault("expected_selectors", eval_record.get("expected_selectors", []))
        item.setdefault("expected_action_types", eval_record.get("expected_action_types", []))
    return item


def build_scenario_choices(scenarios: list[dict]) -> list[dict]:
    enriched: list[tuple[dict, str]] = []
    for scenario in scenarios:
        item = enrich_scenario_metadata(scenario)
        key = scenario_key(item)
        copy = SCENARIO_COPY.get(key, {})
        title = copy.get("title", fallback_title(str(item.get("name", "Scenario"))))
        item["description"] = item.get("description") or copy.get("description", "A healthcare web workflow is executed and compared side by side.")
        enriched.append((item, title))

    totals = Counter(title for _, title in enriched)
    seen: Counter[str] = Counter()
    choices = []
    for item, title in enriched:
        seen[title] += 1
        item["display_name"] = f"{title} - Case {seen[title]}" if totals[title] > 1 else title
        choices.append(item)
    return choices


def clean_json_response(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        if len(parts) >= 2:
            cleaned = parts[1].strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
    return cleaned


def parse_json_response(raw: str) -> tuple[dict | None, list[dict]]:
    try:
        parsed = json.loads(clean_json_response(raw))
    except json.JSONDecodeError:
        return None, []
    actions = parsed.get("actions", []) if isinstance(parsed, dict) else []
    return parsed, [action for action in actions if isinstance(action, dict)]


def normalize_selector(selector: object) -> str:
    if not isinstance(selector, str):
        return ""
    return re.sub(r"\s+", "", selector.strip().replace('"', "'"))


def looks_like_css_selector(selector: object) -> bool:
    if not isinstance(selector, str) or not selector.strip():
        return False
    stripped = selector.strip()
    return stripped.startswith(("#", ".", "[")) or "#" in stripped or "[" in stripped


def canonical_action(action: dict) -> tuple:
    action_type = action.get("type")
    signature = [action_type, normalize_selector(action.get("selector"))]
    if action_type == "type":
        signature.append(str(action.get("value", "")))
    if action_type == "extract":
        signature.append(str(action.get("as", "")))
    return tuple(signature)


def selector_label(selector: str | None) -> str:
    if not selector:
        return "unknown target"
    match = re.search(r"data-eim-(?:action|field|value)=['\"]([^'\"]+)['\"]", selector)
    if match:
        return match.group(1).replace("-", " ")
    return selector


def explain_actions(raw: str) -> list[str]:
    _, actions = parse_json_response(raw)
    if not actions:
        return ["No structured actions were returned."]
    steps = []
    for index, action in enumerate(actions, start=1):
        action_type = action.get("type", "action")
        selector = action.get("selector")
        target = selector_label(selector)
        if action_type == "type":
            steps.append(f"{index}. Type `{action.get('value', '')}` into `{target}`")
        elif action_type == "click":
            steps.append(f"{index}. Click `{target}`")
        elif action_type == "extract":
            steps.append(f"{index}. Extract `{action.get('as', 'value')}` from `{target}`")
        else:
            steps.append(f"{index}. {action_type} `{target}`")
    return steps


def score_response(raw: str, scenario: dict) -> dict[str, bool]:
    parsed, actions = parse_json_response(raw)
    expected_selectors = {normalize_selector(selector) for selector in scenario.get("expected_selectors", [])}
    expected_types = scenario.get("expected_action_types", [])
    gold_actions = scenario.get("gold", {}).get("actions", []) if scenario.get("gold") else []
    selectors = {normalize_selector(action.get("selector")) for action in actions}
    action_types = [action.get("type") for action in actions]
    gold_signatures = Counter(canonical_action(action) for action in gold_actions)
    action_signatures = Counter(canonical_action(action) for action in actions)
    schema_ok = (
        isinstance(parsed, dict)
        and bool(actions)
        and all("type" in action and "selector" in action for action in actions)
    )
    return {
        "Valid JSON": parsed is not None,
        "Action schema": schema_ok,
        "Selector validity": schema_ok and all(looks_like_css_selector(action.get("selector")) for action in actions),
        "Stable EIM selectors": bool(expected_selectors) and expected_selectors.issubset(selectors),
        "Workflow navigation": any(normalize_selector(action.get("selector", "")).startswith("[data-eim-action='open-") for action in actions),
        "Required actions": bool(gold_actions) and all(action_signatures[action] >= count for action, count in gold_signatures.items()),
        "Correct order": bool(expected_types) and action_types[: len(expected_types)] == expected_types,
        "Exact action match": bool(gold_actions) and [canonical_action(action) for action in actions] == [canonical_action(action) for action in gold_actions],
    }


def load_eval_summary() -> dict[str, int] | None:
    if not RESULTS_FILE.exists():
        return None
    try:
        details = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    base_total = sum(sum(bool(value) for value in item.get("base_score", {}).values()) for item in details)
    tuned_total = sum(sum(bool(value) for value in item.get("ft_score", {}).values()) for item in details)
    max_total = sum(max(len(item.get("base_score", {})), len(item.get("ft_score", {}))) for item in details)
    return {"base": base_total, "tuned": tuned_total, "max": max_total, "delta": tuned_total - base_total}


def load_endpoint_info() -> tuple[EndpointInfo, str | None]:
    try:
        return refresh_endpoint_info(), None
    except Exception as exc:
        endpoint_name = os.environ.get("ENDPOINT_NAME", DEFAULT_ENDPOINT_NAME)
        return EndpointInfo(name=endpoint_name, scoring_uri=None, primary_key=None), str(exc)


def render_lifecycle_output() -> None:
    output = st.session_state.get("lifecycle_output")
    if output:
        with st.sidebar.expander("Last lifecycle command", expanded=False):
            st.code(output[-6000:], language="text")


def run_lifecycle_action(label: str, script_name: str, *args: str) -> None:
    with st.spinner(label):
        result = run_step_script(script_name, *args)
    combined = "\n".join(part for part in [result.stdout, result.stderr] if part.strip())
    st.session_state["lifecycle_output"] = combined or f"{script_name} exited with {result.returncode}."
    if result.returncode == 0:
        st.sidebar.success("Done")
    else:
        st.sidebar.error(f"Command failed with exit code {result.returncode}")


def append_turn(prompt: str, base_response: str, tuned_response: str, scenario: dict) -> None:
    st.session_state.setdefault("turns", [])
    st.session_state["turns"].append(
        {
            "prompt": prompt,
            "base": base_response,
            "tuned": tuned_response,
            "scenario": scenario,
        }
    )


def render_response(raw: str, view_mode: str) -> None:
    if view_mode == "Explain actions":
        for step in explain_actions(raw):
            st.markdown(step)
        with st.expander("Raw JSON", expanded=False):
            st.code(raw, language="json")
    else:
        st.code(raw, language="json")


def render_score_breakdown(turn: dict) -> None:
    scenario = enrich_scenario_metadata(turn.get("scenario", {}), turn.get("prompt"))
    base_scores = score_response(turn["base"], scenario)
    tuned_scores = score_response(turn["tuned"], scenario)
    rows = []
    for check in base_scores:
        rows.append({
            "Check": check,
            "Base Gemma": "Pass" if base_scores[check] else "Miss",
            "Fine-tuned Gemma": "Pass" if tuned_scores[check] else "Miss",
        })
    st.table(rows)


def render_why_panel(turn: dict) -> None:
    _, base_actions = parse_json_response(turn["base"])
    _, tuned_actions = parse_json_response(turn["tuned"])
    base_dynamic = sum(1 for action in base_actions if "#" in str(action.get("selector", "")))
    tuned_stable = sum(1 for action in tuned_actions if str(action.get("selector", "")).startswith("[data-eim-"))
    st.markdown("#### Why the Tuned Model Helps")
    st.info(
        "The base model often uses brittle generated IDs, while the fine-tuned path uses stable Molina/EIM workflow selectors. "
        f"In this run, base used {base_dynamic} ID-based selectors and fine-tuned returned {tuned_stable} stable EIM selectors."
    )


st.set_page_config(
    page_title="Molina Gemma 4B Fine-Tune Demo",
    page_icon="M",
    layout="wide",
)

st.markdown(
    """
    <style>
    :root {
        --demo-ink: #18212f;
        --demo-muted: #5a687a;
        --demo-blue: #1267b3;
        --demo-green: #167a5b;
        --demo-border: #d7dee8;
        --demo-panel: #f7f9fc;
        --demo-warn: #8a4b00;
    }
    .main .block-container {
        padding-top: 1.4rem;
        padding-bottom: 2rem;
        max-width: 1400px;
    }
    h1, h2, h3 {
        letter-spacing: 0;
        color: var(--demo-ink);
    }
    .demo-kicker {
        color: var(--demo-muted);
        font-size: 0.95rem;
        margin-top: -0.6rem;
        margin-bottom: 1.2rem;
    }
    .endpoint-live {
        border: 1px solid #f0c36a;
        background: #fff8e8;
        color: var(--demo-warn);
        border-radius: 8px;
        padding: 0.75rem 0.9rem;
        margin-bottom: 0.85rem;
        font-weight: 600;
    }
    .endpoint-off {
        border: 1px solid var(--demo-border);
        background: var(--demo-panel);
        color: var(--demo-muted);
        border-radius: 8px;
        padding: 0.75rem 0.9rem;
        margin-bottom: 0.85rem;
        font-weight: 600;
    }
    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 8px;
    }
    .response-label {
        font-weight: 700;
        margin-bottom: 0.25rem;
    }
    .response-label.base {
        color: var(--demo-blue);
    }
    .response-label.tuned {
        color: var(--demo-green);
    }
    div[data-testid="stCodeBlock"] pre {
        min-height: 220px;
        max-height: 420px;
        overflow: auto;
        white-space: pre-wrap;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

state = load_state()
endpoint_variants = state.get("endpoint_variants", [])
fine_tuned_available = "fine_tuned" in endpoint_variants
endpoint_info, endpoint_error = load_endpoint_info()

with st.sidebar:
    st.header("Endpoint")
    if endpoint_info.is_ready:
        st.markdown("<div class='endpoint-live'>A100 endpoint is live. Delete it when the demo ends.</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div class='endpoint-off'>No ready A100 endpoint detected.</div>", unsafe_allow_html=True)

    st.write(f"Name: `{endpoint_info.name}`")
    st.write(f"State: `{endpoint_info.provisioning_state or 'not found'}`")
    if endpoint_error:
        st.caption(endpoint_error)

    if st.button("Refresh status", use_container_width=True):
        st.rerun()
    deploy_script = "04_register_and_deploy.py" if state.get("training_job_name") else "04_deploy_catalog_model.py"
    deploy_label = "Create or update fine-tuned endpoint" if state.get("training_job_name") else "Create or update catalog endpoint"
    if st.button(deploy_label, type="primary", use_container_width=True):
        run_lifecycle_action("Creating AzureML endpoint. First deployment can take 10-20 minutes.", deploy_script)
        st.rerun()
    if st.button("Delete AML endpoint", use_container_width=True):
        run_lifecycle_action("Deleting AzureML endpoint to stop A100 billing.", "06_cleanup.py", "--yes")
        st.rerun()

    render_lifecycle_output()

st.title("Molina EIM Gemma 4 E2B")
st.markdown(
    f"<div class='demo-kicker'>Catalog model `{GEMMA_MODEL_ID}` from `{GEMMA_CATALOG_MODEL_ID}` is served from an AzureML A100 endpoint. Fine-tuned comparison appears after the LoRA adapter is deployed.</div>",
    unsafe_allow_html=True,
)

summary = load_eval_summary()
if summary:
    metric_cols = st.columns(3)
    metric_cols[0].metric("Base Gemma", f"{summary['base']}/{summary['max']}")
    metric_cols[1].metric("Fine-tuned", f"{summary['tuned']}/{summary['max']}")
    metric_cols[2].metric("Fine-tuned lift", f"+{summary['delta']}")

st.markdown(
    "This demo compares generic web-action output against Molina/EIM-ready automation output. "
    "The goal is stable workflow selectors, complete action order, and reusable automation plans."
)

scenario_choices = build_scenario_choices(DEMO_SCENARIOS)
scenario_names = [scenario["display_name"] for scenario in scenario_choices]
selected_name = st.selectbox("Scenario", scenario_names)
selected_scenario = next(scenario for scenario in scenario_choices if scenario["display_name"] == selected_name)
st.text_area(
    "Scenario in simple English",
    value=selected_scenario.get("description", "A healthcare web workflow is executed and compared side by side."),
    height=90,
    disabled=True,
)
view_mode = st.radio("Response view", ["Explain actions", "Raw JSON"], horizontal=True)

prompt = st.text_area(
    "Prompt",
    value=selected_scenario["prompt"],
    height=220,
)
max_new_tokens = st.slider("Max new tokens", min_value=80, max_value=600, value=300, step=20)

send_clicked = st.button("Send to both models", type="primary", disabled=not endpoint_info.is_ready)
if send_clicked:
    messages = build_messages(prompt)
    try:
        with st.spinner("Calling catalog Gemma 4 E2B..."):
            base_response = call_endpoint(
                messages,
                use_adapter=False,
                max_new_tokens=max_new_tokens,
                endpoint_info=endpoint_info,
            )
        if fine_tuned_available:
            with st.spinner("Calling fine-tuned Gemma 4 E2B..."):
                tuned_response = call_endpoint(
                    messages,
                    use_adapter=True,
                    max_new_tokens=max_new_tokens,
                    endpoint_info=endpoint_info,
                )
        else:
            tuned_response = "Fine-tuned adapter is not deployed yet. Run training, then create the fine-tuned endpoint."
        append_turn(prompt, base_response, tuned_response, selected_scenario)
    except Exception as exc:
        st.error(str(exc))

turns = st.session_state.get("turns", [])
if turns:
    render_why_panel(turns[-1])
    st.markdown("#### Response Score Breakdown")
    render_score_breakdown(turns[-1])

base_col, tuned_col = st.columns(2, gap="large")

with base_col:
    st.subheader("Gemma 4 E2B Catalog")
    if not turns:
        st.info("Send a scenario to compare raw Gemma 4B behavior.")
    for turn in reversed(turns):
        st.markdown("<div class='response-label base'>Assistant response</div>", unsafe_allow_html=True)
        render_response(turn["base"], view_mode)
        with st.expander("Prompt", expanded=False):
            st.code(turn["prompt"], language="text")

with tuned_col:
    st.subheader("Gemma 4 E2B Fine-Tuned")
    if not turns:
        st.info("Send a scenario to compare adapter-enabled behavior.")
    for turn in reversed(turns):
        st.markdown("<div class='response-label tuned'>Assistant response</div>", unsafe_allow_html=True)
        render_response(turn["tuned"], view_mode)
        with st.expander("Prompt", expanded=False):
            st.code(turn["prompt"], language="text")