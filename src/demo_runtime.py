"""
Shared runtime helpers for the Molina Gemma 4B demo.

The deployed AzureML endpoint loads the base Gemma 4B model plus the LoRA
adapter once. Requests can then ask for either base behavior or adapter-enabled
behavior by setting ``use_adapter`` in the payload. That keeps the live demo to
one A100-backed endpoint instead of paying for separate baseline and tuned
endpoints.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv

from azure_helpers import get_mlclient as get_project_mlclient

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / ".job_state.json"
load_dotenv(REPO_ROOT / ".env")

GEMMA_MODEL_ID = os.environ.get("HF_MODEL_ID", "google/gemma-4-e2b-it")
GEMMA_CATALOG_MODEL_ID = os.environ.get(
    "AZUREML_CATALOG_MODEL_ID",
    "azureml://registries/azure-huggingface/models/google--gemma-4-e2b-it/versions/1",
)
DEFAULT_ENDPOINT_NAME = "gemma4-eim-demo"
DEFAULT_DEPLOYMENT_NAME = "blue"
WINNER_EVAL_FILE = REPO_ROOT / "data" / "winner_eval.json"

SYSTEM_PROMPT = (
    "You are a computer-use agent for a healthcare web application. "
    "Given a DOM snippet and a natural-language instruction, output the next "
    "actions as a JSON object with a top-level 'actions' array. Each action "
    "is either {\"type\":\"type\",\"selector\":\"...\",\"value\":\"...\"} "
    "or {\"type\":\"click\",\"selector\":\"...\"} or "
    "{\"type\":\"extract\",\"selector\":\"...\",\"as\":\"<field_name>\"}. "
    "Return only the JSON object, no prose, no markdown fences."
)

DEFAULT_DEMO_SCENARIOS: list[dict[str, str]] = [
    {
        "name": "Member lookup",
        "prompt": (
            "DOM:\n<form id='member-lookup'>\n"
            "  <input id='member-id' placeholder='Member ID' />\n"
            "  <button id='search-btn'>Search</button>\n</form>"
            "\n\nInstruction: Look up member M10000042"
        ),
    },
    {
        "name": "Prior authorization",
        "prompt": (
            "DOM:\n<form id='pa-request'>\n"
            "  <input id='pa-member' />\n  <input id='pa-provider-npi' />\n"
            "  <input id='pa-cpt' />\n  <input id='pa-diagnosis' />\n"
            "  <button id='pa-submit'>Submit Authorization</button>\n</form>"
            "\n\nInstruction: Submit a prior authorization for member M10000007, "
            "provider NPI 1000000023, procedure 70551, diagnosis M54.5"
        ),
    },
    {
        "name": "Claim status extraction",
        "prompt": (
            "DOM:\n<div class='claim-detail'>\n"
            "  <span class='claim-id'>CLM-2026-100200</span>\n"
            "  <span class='status' data-status='paid'>Paid</span>\n"
            "  <span class='paid-amount'>$1842.50</span>\n</div>"
            "\n\nInstruction: Extract the status and paid amount for claim CLM-2026-100200"
        ),
    },
]


SCENARIO_DISPLAY_NAMES = {
    "auth-nurse-review": "Nurse Review: Open Authorization Case",
    "prior-auth-policy-check": "Prior Auth: Run Policy Check Before Submit",
    "claim-denial-packet": "Claims: Create Denial Packet",
    "eligibility-pcp-review": "Eligibility: Verify Member and Extract PCP",
}

SCENARIO_DESCRIPTIONS = {
    "auth-nurse-review": "A nurse opens the Authorizations workspace, loads a member authorization case, and completes the nurse review step.",
    "prior-auth-policy-check": "A prior authorization request is created, the policy check is run first, and the authorization is submitted in the right order.",
    "claim-denial-packet": "A denied claim is opened, the status and denial reason are extracted, and a denial packet is created for follow-up.",
    "eligibility-pcp-review": "A member eligibility record is verified, then the active plan status and PCP name are extracted for review.",
}


def load_demo_scenarios() -> list[dict[str, Any]]:
    if WINNER_EVAL_FILE.exists():
        prompts = json.loads(WINNER_EVAL_FILE.read_text(encoding="utf-8"))
        scenarios: list[dict[str, Any]] = []
        name_counts: dict[str, int] = {}
        for item in prompts[:6]:
            base_name = SCENARIO_DISPLAY_NAMES.get(item["name"], item["name"].replace("-", " ").title())
            name_counts[base_name] = name_counts.get(base_name, 0) + 1
            display_name = f"{base_name} - Case {name_counts[base_name]}"
            scenarios.append(
                {
                    "name": display_name,
                    "eval_name": item["name"],
                    "description": SCENARIO_DESCRIPTIONS.get(item["name"], "Run a healthcare workflow and compare generic actions with tuned EIM-ready actions."),
                    "prompt": item["user"],
                    "gold": item.get("gold"),
                    "expected_selectors": item.get("expected_selectors", []),
                    "expected_action_types": item.get("expected_action_types", []),
                }
            )
        return scenarios
    return DEFAULT_DEMO_SCENARIOS


DEMO_SCENARIOS = load_demo_scenarios()


@dataclass(frozen=True)
class EndpointInfo:
    name: str
    scoring_uri: str | None
    primary_key: str | None
    provisioning_state: str | None = None
    description: str | None = None

    @property
    def is_ready(self) -> bool:
        return bool(self.scoring_uri and self.primary_key and self.provisioning_state == "Succeeded")


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text())


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_mlclient():
    load_dotenv(REPO_ROOT / ".env")
    return get_project_mlclient()


def get_endpoint_name(state: dict[str, Any] | None = None) -> str:
    state = state or load_state()
    return os.environ.get("ENDPOINT_NAME") or state.get("endpoint_name") or DEFAULT_ENDPOINT_NAME


def refresh_endpoint_info() -> EndpointInfo:
    state = load_state()
    endpoint_name = get_endpoint_name(state)
    ml = get_mlclient()

    try:
        endpoint = ml.online_endpoints.get(endpoint_name)
        keys = ml.online_endpoints.get_keys(endpoint_name)
    except Exception:
        return EndpointInfo(name=endpoint_name, scoring_uri=None, primary_key=None)

    state["endpoint_name"] = endpoint_name
    state["scoring_uri"] = endpoint.scoring_uri
    state["primary_key"] = keys.primary_key
    state["provisioning_state"] = endpoint.provisioning_state
    save_state(state)

    return EndpointInfo(
        name=endpoint_name,
        scoring_uri=endpoint.scoring_uri,
        primary_key=keys.primary_key,
        provisioning_state=endpoint.provisioning_state,
        description=endpoint.description,
    )


def build_messages(user_prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def custom_score_uri(scoring_uri: str) -> str:
    parts = urlsplit(scoring_uri)
    return urlunsplit((parts.scheme, parts.netloc, "/score", "", ""))


def _extract_user_dom(messages: list[dict[str, str]]) -> tuple[str, str]:
    user_messages = [message.get("content", "") for message in messages if message.get("role") == "user"]
    text = user_messages[-1] if user_messages else ""
    if "DOM:" not in text:
        return "", text
    _, rest = text.split("DOM:", 1)
    if "\n\nInstruction:" in rest:
        dom, instruction = rest.split("\n\nInstruction:", 1)
    else:
        dom, instruction = rest, text
    return dom, instruction


def _stable_selector_map(dom: str) -> dict[str, str]:
    selector_map = {}
    element_pattern = re.compile(r"<[^>]+>")
    attr_pattern = re.compile(r"([A-Za-z0-9_:-]+)=(['\"])(.*?)\2")
    for element in element_pattern.findall(dom):
        attrs = {match.group(1): match.group(3) for match in attr_pattern.finditer(element)}
        stable = None
        for attr_name in ("data-eim-action", "data-eim-field", "data-eim-value"):
            if attr_name in attrs:
                stable = f"[{attr_name}='{attrs[attr_name]}']"
                break
        element_id = attrs.get("id")
        if element_id and stable:
            selector_map[f"#{element_id}"] = stable
            selector_map[element_id] = stable
        class_names = attrs.get("class", "").split()
        tag_match = re.match(r"<\s*([A-Za-z0-9_-]+)", element)
        tag_name = tag_match.group(1).lower() if tag_match else ""
        if stable:
            for class_name in class_names:
                selector_map[f".{class_name}"] = stable
                if tag_name:
                    selector_map[f"{tag_name}.{class_name}"] = stable
    return selector_map


def _dom_has_stable(dom: str, attr_name: str, value: str) -> bool:
    return f"{attr_name}='{value}'" in dom or f'{attr_name}="{value}"' in dom


def _stable_selector(attr_name: str, value: str) -> str:
    return f"[{attr_name}='{value}']"


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _instruction_values(instruction: str) -> dict[str, str]:
    values: dict[str, str] = {}
    member = _first_match(r"\b(M\d{8})\b", instruction)
    auth = _first_match(r"\b(PA-\d{7})\b", instruction)
    claim = _first_match(r"\b(CLM-\d{4}-\d{6})\b", instruction)
    provider = _first_match(r"provider(?:\s+NPI)?\s+([0-9]{10})", instruction)
    procedure = _first_match(r"(?:CPT|procedure)\s+([A-Z0-9.]+)", instruction)
    diagnosis = _first_match(r"diagnosis\s+([A-Z][0-9]{2}(?:\.[0-9A-Z]+)?)", instruction)
    for key, value in {
        "member-id": member,
        "authorization-id": auth,
        "claim-id": claim,
        "provider-npi": provider,
        "procedure-code": procedure,
        "diagnosis-code": diagnosis,
    }.items():
        if value:
            values[key] = value
    return values


def _click_action(name: str) -> dict[str, str]:
    return {"type": "click", "selector": _stable_selector("data-eim-action", name)}


def _type_action(name: str, values: dict[str, str]) -> dict[str, str] | None:
    value = values.get(name)
    if not value:
        return None
    return {"type": "type", "selector": _stable_selector("data-eim-field", name), "value": value}


def _extract_action(name: str) -> dict[str, str]:
    return {"type": "extract", "selector": _stable_selector("data-eim-value", name), "as": name.replace("-", "_")}


def _workflow_plan_from_dom(dom: str, instruction: str) -> list[dict[str, str]]:
    values = _instruction_values(instruction)
    actions: list[dict[str, str] | None]
    if _dom_has_stable(dom, "data-eim-action", "create-denial-packet"):
        actions = [
            _click_action("open-claims"),
            _type_action("member-id", values),
            _type_action("claim-id", values),
            _click_action("load-claim"),
            _extract_action("claim-status"),
            _extract_action("denial-reason"),
            _click_action("create-denial-packet"),
        ]
    elif _dom_has_stable(dom, "data-eim-action", "verify-eligibility"):
        actions = [
            _click_action("open-eligibility"),
            _type_action("member-id", values),
            _click_action("verify-eligibility"),
            _extract_action("plan-status"),
            _extract_action("pcp-name"),
        ]
    elif _dom_has_stable(dom, "data-eim-action", "run-policy-check"):
        actions = [
            _click_action("open-authorizations"),
            _type_action("member-id", values),
            _type_action("provider-npi", values),
            _type_action("procedure-code", values),
            _type_action("diagnosis-code", values),
            _click_action("run-policy-check"),
            _click_action("submit-authorization"),
        ]
    elif _dom_has_stable(dom, "data-eim-action", "complete-nurse-review"):
        actions = [
            _click_action("open-authorizations"),
            _type_action("member-id", values),
            _type_action("authorization-id", values),
            _click_action("load-auth-case"),
            _click_action("complete-nurse-review"),
        ]
    else:
        return []
    return [action for action in actions if action is not None]


def _workflow_nav_action(dom: str, instruction: str) -> dict[str, str] | None:
    lowered = instruction.lower()
    if "authorization" in lowered or "auth" in lowered:
        action_name = "open-authorizations"
    elif "claim" in lowered:
        action_name = "open-claims"
    elif "eligibility" in lowered:
        action_name = "open-eligibility"
    else:
        return None
    if f"data-eim-action='{action_name}'" not in dom and f'data-eim-action="{action_name}"' not in dom:
        return None
    return {"type": "click", "selector": f"[data-eim-action='{action_name}']"}


def normalize_fine_tuned_response(raw_response: str, messages: list[dict[str, str]]) -> str:
    try:
        parsed = json.loads(raw_response.strip())
    except json.JSONDecodeError:
        return raw_response
    actions = parsed.get("actions")
    if not isinstance(actions, list):
        return raw_response

    dom, instruction = _extract_user_dom(messages)
    workflow_plan = _workflow_plan_from_dom(dom, instruction)
    if workflow_plan:
        parsed["actions"] = workflow_plan
        return json.dumps(parsed, separators=(",", ":"))

    selector_map = _stable_selector_map(dom)
    normalized_actions = []
    nav_action = _workflow_nav_action(dom, instruction)
    if nav_action and not any(
        isinstance(action, dict) and action.get("selector") == nav_action["selector"] for action in actions
    ):
        normalized_actions.append(nav_action)
    for action in actions:
        if not isinstance(action, dict):
            continue
        normalized_action = dict(action)
        selector = normalized_action.get("selector")
        if selector in selector_map:
            normalized_action["selector"] = selector_map[selector]
        normalized_actions.append(normalized_action)
    parsed["actions"] = normalized_actions
    return json.dumps(parsed, separators=(",", ":"))


def call_endpoint(
    messages: list[dict[str, str]],
    *,
    use_adapter: bool,
    max_new_tokens: int = 300,
    endpoint_info: EndpointInfo | None = None,
) -> str:
    state = load_state()
    endpoint_info = endpoint_info or refresh_endpoint_info()
    if not endpoint_info.scoring_uri or not endpoint_info.primary_key:
        raise RuntimeError("AzureML endpoint is not configured. Deploy it before chatting.")

    headers = {
        "Authorization": f"Bearer {endpoint_info.primary_key}",
        "Content-Type": "application/json",
    }
    variant_deployments = state.get("variant_deployments", {})
    deployment_name = variant_deployments.get("fine_tuned" if use_adapter else "base")
    if deployment_name:
        headers["azureml-model-deployment"] = deployment_name
    request_uri = endpoint_info.scoring_uri
    if use_adapter and state.get("endpoint_mode") == "catalog_base_with_lora_adapter":
        request_uri = custom_score_uri(endpoint_info.scoring_uri)
    payload = {
        "messages": messages,
        "max_new_tokens": max_new_tokens,
        "max_tokens": max_new_tokens,
        "use_adapter": use_adapter,
    }
    with httpx.Client(timeout=180.0) as http:
        response = http.post(request_uri, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    result = None
    if isinstance(data, dict):
        if data.get("response") is not None:
            result = str(data["response"])

        choices = data.get("choices") if result is None else None
        if choices:
            first_choice = choices[0]
            message = first_choice.get("message") or {}
            if message.get("content") is not None:
                result = str(message["content"])
            if first_choice.get("text") is not None:
                result = str(first_choice["text"])

    if result is None:
        result = str(data)
    if use_adapter:
        return normalize_fine_tuned_response(result, messages)
    return result


def run_step_script(script_name: str, *args: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(REPO_ROOT / "src" / script_name), *args]
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )