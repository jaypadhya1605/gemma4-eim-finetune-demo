"""Grant the current Azure principal data-plane roles needed by local setup."""

from __future__ import annotations

import base64
import json
import os
import uuid

import requests
from rich.console import Console
from rich.panel import Panel

from azure_helpers import get_credential, load_project_env


ARM_ENDPOINT = "https://management.azure.com"
API_ROLE_ASSIGNMENTS = "2022-04-01"
API_WORKSPACES = "2024-10-01"
STORAGE_ROLES = {
    "Storage Blob Data Reader": "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1",
    "Storage Blob Data Contributor": "ba92f5b4-2d11-453d-a403-e96b0029c9fe",
}
KEY_VAULT_ROLES = {
    "Key Vault Secrets Officer": "b86a8fe4-44ce-4948-aee5-eccb2c155cd7",
}


console = Console()


def _decode_claims(access_token: str) -> dict[str, object]:
    payload = access_token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))


def _arm_request(method: str, path: str, token: str, **kwargs) -> requests.Response:
    response = requests.request(
        method,
        f"{ARM_ENDPOINT}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=60,
        **kwargs,
    )
    return response


def _workspace_scopes(subscription_id: str, resource_group: str, workspace_name: str, token: str) -> tuple[str, str]:
    workspace_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.MachineLearningServices/workspaces/{workspace_name}"
    )
    response = _arm_request("GET", f"{workspace_id}?api-version={API_WORKSPACES}", token)
    response.raise_for_status()
    properties = response.json()["properties"]
    return properties["storageAccount"], properties["keyVault"]


def _assign_role(subscription_id: str, scope: str, principal_id: str, role_name: str, role_id: str, token: str) -> None:
    role_definition_id = f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization/roleDefinitions/{role_id}"
    assignment_name = uuid.uuid5(uuid.NAMESPACE_URL, f"{scope}|{principal_id}|{role_id}")
    assignment_path = (
        f"{scope}/providers/Microsoft.Authorization/roleAssignments/{assignment_name}"
        f"?api-version={API_ROLE_ASSIGNMENTS}"
    )
    response = _arm_request(
        "PUT",
        assignment_path,
        token,
        json={
            "properties": {
                "roleDefinitionId": role_definition_id,
                "principalId": principal_id,
            }
        },
    )

    if response.status_code in {200, 201}:
        console.print(f"  assigned: {role_name}")
        return

    try:
        error = response.json().get("error", {})
    except ValueError:
        error = {}
    if response.status_code == 409 and error.get("code") == "RoleAssignmentExists":
        console.print(f"  already assigned: {role_name}")
        return

    response.raise_for_status()


def main() -> None:
    load_project_env()
    subscription_id = os.environ["AZURE_SUBSCRIPTION_ID"]
    resource_group = os.environ["AZURE_RESOURCE_GROUP"]
    workspace_name = os.environ["AZUREML_WORKSPACE_NAME"]

    console.print(Panel.fit("Step 00b - Grant local setup RBAC", border_style="cyan"))
    credential = get_credential()
    token = credential.get_token("https://management.azure.com/.default").token
    claims = _decode_claims(token)
    principal_id = str(claims.get("oid") or "")
    if not principal_id:
        raise RuntimeError("The Azure access token did not include an object id (oid) claim.")

    principal_name = claims.get("upn") or claims.get("preferred_username") or claims.get("appid") or principal_id
    storage_scope, key_vault_scope = _workspace_scopes(subscription_id, resource_group, workspace_name, token)

    console.print(f"  principal: {principal_name}")
    console.print(f"  principal object id: {principal_id}")
    console.print(f"  storage scope: {storage_scope}")
    console.print(f"  key vault scope: {key_vault_scope}")

    for role_name, role_id in STORAGE_ROLES.items():
        _assign_role(subscription_id, storage_scope, principal_id, role_name, role_id, token)
    for role_name, role_id in KEY_VAULT_ROLES.items():
        _assign_role(subscription_id, key_vault_scope, principal_id, role_name, role_id, token)

    console.print("\nLocal setup RBAC is ready. Role propagation can take a few minutes.")


if __name__ == "__main__":
    main()