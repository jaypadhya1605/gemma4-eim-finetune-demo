// infra/main.bicep
// =================
// AzureML workspace + supporting resources + A100 compute cluster for the
// Gemma 4B LoRA fine-tuning demo.
//
// Resources provisioned:
//   - Storage account (workspace default datastore)
//   - Key Vault (for HF_TOKEN secret)
//   - Application Insights (for endpoint telemetry)
//   - Log Analytics Workspace (backing AppInsights)
//   - AzureML workspace
//   - Compute cluster: 1-node A100 (auto-scales 0→1)
//   - Role assignment: caller → AzureML Data Scientist
//
// Deploy:
//   az deployment group create \
//     --resource-group <rg> \
//     --template-file infra/main.bicep \
//     --parameters workspaceName=<ws> location=eastus2 \
//                  principalId=$(az ad signed-in-user show --query id -o tsv)
//
// Prereq: subscription quota for at least 24 cores of NCADS A100 v4 family
// in the chosen region.

@description('AzureML workspace name (lowercase, 3-33 chars).')
@minLength(3)
@maxLength(33)
param workspaceName string

@description('Azure region. Must have A100 quota.')
@allowed([
  'eastus'
  'eastus2'
  'southcentralus'
  'westus3'
  'swedencentral'
])
param location string = 'eastus2'

@description('AAD object ID of the principal that needs AzureML Data Scientist + KV access.')
param principalId string

@description('Compute cluster size — Standard_NC24ads_A100_v4 = 1× A100 80GB, 24 vCPUs.')
param computeSku string = 'Standard_NC24ads_A100_v4'

@description('Tags for cost tracking.')
param tags object = {
  workload: 'molina-eim-gemma4-finetune'
  owner: 'jay.padhya@microsoft.com'
  environment: 'demo'
}

var suffix = uniqueString(resourceGroup().id, workspaceName)
var storageName = take(toLower(replace('st${workspaceName}${suffix}', '-', '')), 24)
var kvName = take(toLower(replace('kv${workspaceName}${take(suffix, 6)}', '-', '')), 24)
var aiName = 'ai-${workspaceName}'
var lawName = 'law-${workspaceName}'

// -- Storage account ---------------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: any(storageName)
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    encryption: {
      services: {
        blob: { enabled: true }
        file: { enabled: true }
      }
      keySource: 'Microsoft.Storage'
    }
  }
}

// -- Key Vault (holds HF_TOKEN) ---------------------------------------------
resource kv 'Microsoft.KeyVault/vaults@2024-04-01-preview' = {
  name: kvName
  location: location
  tags: tags
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true   // RBAC-based, not access policies
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled'  // tighten in prod
  }
}

// -- Log Analytics + App Insights -------------------------------------------
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: lawName
  location: location
  tags: tags
  properties: { retentionInDays: 30, sku: { name: 'PerGB2018' } }
}

resource ai 'Microsoft.Insights/components@2020-02-02' = {
  name: aiName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

// -- AzureML workspace ------------------------------------------------------
resource ws 'Microsoft.MachineLearningServices/workspaces@2024-10-01' = {
  name: workspaceName
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  sku: { name: 'Basic', tier: 'Basic' }
  properties: any({
    friendlyName: 'Molina EIM — Gemma 4B fine-tune'
    description: 'AzureML workspace for the Gemma 4B LoRA SFT demo. Synthetic data only.'
    storageAccount: storage.id
    keyVault: kv.id
    applicationInsights: ai.id
    systemDatastoresAuthMode: 'identity'
    publicNetworkAccess: 'Enabled' // tighten in prod
  })
}

// -- Compute cluster (auto-scaling 0→1 A100) --------------------------------
resource computeCluster 'Microsoft.MachineLearningServices/workspaces/computes@2024-10-01' = {
  parent: ws
  name: 'a100-cluster-1node'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    computeType: 'AmlCompute'
    properties: {
      vmSize: computeSku
      vmPriority: 'Dedicated'      // 'LowPriority' = spot; cheaper but interruptible
      scaleSettings: {
        minNodeCount: 0
        maxNodeCount: 1
        nodeIdleTimeBeforeScaleDown: 'PT15M'  // scale to 0 after 15 min idle
      }
      osType: 'Linux'
      enableNodePublicIp: true     // disable in production + use VNet-attached cluster
    }
  }
}

// -- Role assignment: principal → AzureML Data Scientist on workspace -------
var dataScientistRoleId = 'f6c7c914-8db3-469d-8ca1-694a8f32e121'

resource dataScientistRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(ws.id, principalId, dataScientistRoleId)
  scope: ws
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', dataScientistRoleId)
    principalId: principalId
    principalType: 'User'
  }
}

// -- Role assignment: principal → Key Vault Secrets Officer ----------------
var kvSecretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'

resource kvSecretsOfficerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, principalId, kvSecretsOfficerRoleId)
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsOfficerRoleId)
    principalId: principalId
    principalType: 'User'
  }
}

// -- Outputs ----------------------------------------------------------------
output workspaceName string = ws.name
output workspaceId string = ws.id
output computeName string = computeCluster.name
output keyVaultName string = kv.name
output appInsightsName string = ai.name
output storageAccountName string = storage.name
