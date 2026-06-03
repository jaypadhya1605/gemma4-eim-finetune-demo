"""
Step 00 — deploy the AzureML workspace and one-node A100 compute cluster.

This uses the Azure SDK and infra/main.arm.json so it works even when the Azure
CLI is not installed on the workstation.

Run:
    python src/00_deploy_infra.py --validate
    python src/00_deploy_infra.py --deploy
"""
from __future__ import annotations

import argparse
import json
import os
import time

from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.resource.resources.models import Deployment, DeploymentMode, DeploymentProperties
from rich import print as rprint
from rich.panel import Panel

from azure_helpers import REPO_ROOT, get_credential, load_project_env

TEMPLATE_FILE = REPO_ROOT / "infra" / "main.arm.json"


def deployment_parameters() -> dict:
    return {
        "workspaceName": {"value": os.environ["AZUREML_WORKSPACE_NAME"]},
        "location": {"value": os.environ.get("AZURE_REGION", "eastus2")},
        "computeName": {"value": os.environ.get("AZUREML_COMPUTE_NAME", "a100-cluster-1node")},
        "computeSku": {"value": os.environ.get("AZUREML_COMPUTE_SKU", "Standard_NC24ads_A100_v4")},
    }


def build_deployment() -> Deployment:
    template = json.loads(TEMPLATE_FILE.read_text(encoding="utf-8"))
    return Deployment(
        properties=DeploymentProperties(
            mode=DeploymentMode.incremental,
            template=template,
            parameters=deployment_parameters(),
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate", action="store_true", help="Validate the ARM deployment only")
    parser.add_argument("--deploy", action="store_true", help="Create or update the AzureML infrastructure")
    args = parser.parse_args()
    if not args.validate and not args.deploy:
        parser.error("choose --validate or --deploy")

    load_project_env()
    subscription_id = os.environ["AZURE_SUBSCRIPTION_ID"]
    resource_group = os.environ["AZURE_RESOURCE_GROUP"]
    deployment_name = f"aml-gemma4-demo-{int(time.time())}"

    rprint(Panel.fit("[bold]Step 00 — AzureML + A100 infrastructure[/bold]"))
    rprint(f"  subscription: [cyan]{subscription_id}[/cyan]")
    rprint(f"  resource group: [cyan]{resource_group}[/cyan]")
    rprint(f"  workspace: [cyan]{os.environ['AZUREML_WORKSPACE_NAME']}[/cyan]")
    rprint(f"  compute: [cyan]{os.environ.get('AZUREML_COMPUTE_NAME', 'a100-cluster-1node')}[/cyan]")

    client = ResourceManagementClient(get_credential(), subscription_id)
    deployment = build_deployment()

    if args.validate:
        result = client.deployments.begin_validate(resource_group, deployment_name, deployment).result()
        if result.error:
            rprint(f"[red]Validation failed:[/red] {result.error}")
            raise SystemExit(2)
        rprint("[green]Validation succeeded.[/green]")
        return

    poller = client.deployments.begin_create_or_update(resource_group, deployment_name, deployment)
    result = poller.result()
    outputs = result.properties.outputs or {}
    rprint("[green]Deployment complete.[/green]")
    for name, output in outputs.items():
        rprint(f"  {name}: [cyan]{output.get('value')}[/cyan]")


if __name__ == "__main__":
    main()
