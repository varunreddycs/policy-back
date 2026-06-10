@description('Azure location for Container Apps resources.')
param location string

@description('Environment name used for naming and tags.')
param environmentName string

@description('Resource tags to apply.')
param tags object = {}

@description('Container Apps environment name.')
param containerAppsEnvironmentName string

@description('API container app name.')
param apiContainerAppName string

@description('Worker container app name.')
param workerContainerAppName string

@description('Container image for API app.')
param apiImage string

@description('Container image for worker app.')
param workerImage string

@description('ACR login server hostname.')
param acrLoginServer string

@description('ACR resource name for role assignment scope.')
param acrName string

@description('Key Vault URI (e.g. https://kv-name.vault.azure.net/).')
param keyVaultUri string

@description('Key Vault resource name for role assignment scope.')
param keyVaultName string

@description('Storage account name used by app code.')
param storageAccountName string

@description('Raw blob container name for ingestion uploads.')
param rawContainerName string

@description('Extracted blob container name for worker output.')
param extractedContainerName string

@description('Storage queue name for extraction jobs.')
param queueName string

@description('Azure Cosmos DB NoSQL endpoint.')
param cosmosEndpoint string

@description('Cosmos DB database name.')
param cosmosDatabase string = 'policydb'

@description('Azure OpenAI endpoint.')
param azureOpenAiEndpoint string

@description('Azure OpenAI API version.')
param azureOpenAiApiVersion string

@description('Azure OpenAI embeddings deployment name.')
param azureOpenAiEmbeddingsDeployment string

@description('Runtime environment label surfaced to app.')
param appEnvironment string = 'cloud'

@description('Enable FastAPI docs endpoint for API app.')
param enableDocs bool = false

@description('API min replicas.')
param apiMinReplicas int = 1

@description('API max replicas.')
param apiMaxReplicas int = 3

@description('Worker min replicas.')
param workerMinReplicas int = 1

@description('Worker max replicas.')
param workerMaxReplicas int = 2

@description('Embedding dimension.')
param embeddingDim int = 3072

var acrPullRoleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
var keyVaultSecretsUserRoleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${containerAppsEnvironmentName}-logs'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource managedEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerAppsEnvironmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
  }
}

resource acrPullIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${containerAppsEnvironmentName}-acr-pull'
  location: location
  tags: tags
}

resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, acrPullIdentity.id, 'acrpull')
  properties: {
    roleDefinitionId: acrPullRoleDefinitionId
    principalId: acrPullIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource apiApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: apiContainerAppName
  location: location
  tags: union(tags, {
    'azd-service-name': 'api'
    'azd-env-name': environmentName
  })
  identity: {
    type: 'SystemAssigned,UserAssigned'
    userAssignedIdentities: {
      '${acrPullIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: managedEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        allowInsecure: false
        targetPort: 8000
        transport: 'auto'
      }
      registries: [
        {
          server: acrLoginServer
          identity: acrPullIdentity.id
        }
      ]
      secrets: [
        {
          name: 'cosmos-key'
          keyVaultUrl: '${keyVaultUri}secrets/cosmos-key'
          identity: 'system'
        }
        {
          name: 'azure-openai-api-key'
          keyVaultUrl: '${keyVaultUri}secrets/azure-openai-api-key'
          identity: 'system'
        }
        {
          name: 'storage-connection-string'
          keyVaultUrl: '${keyVaultUri}secrets/storage-connection-string'
          identity: 'system'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'policy-api'
          image: apiImage
          env: [
            {
              name: 'ENVIRONMENT'
              value: appEnvironment
            }
            {
              name: 'ENABLE_DOCS'
              value: string(enableDocs)
            }
            {
              name: 'DB_BACKEND'
              value: 'cosmos'
            }
            {
              name: 'COSMOS_ENDPOINT'
              value: cosmosEndpoint
            }
            {
              name: 'COSMOS_KEY'
              secretRef: 'cosmos-key'
            }
            {
              name: 'COSMOS_DATABASE'
              value: cosmosDatabase
            }
            {
              name: 'STORAGE_CONNECTION_STRING'
              secretRef: 'storage-connection-string'
            }
            {
              name: 'AZURE_STORAGE_ACCOUNT_NAME'
              value: storageAccountName
            }
            {
              name: 'AZURE_STORAGE_ACCOUNT_URL'
              value: 'https://${storageAccountName}.blob.${environment().suffixes.storage}'
            }
            {
              name: 'AZURE_STORAGE_QUEUE_ACCOUNT_URL'
              value: 'https://${storageAccountName}.queue.${environment().suffixes.storage}'
            }
            {
              name: 'AZURE_POLICY_RAW_CONTAINER'
              value: rawContainerName
            }
            {
              name: 'AZURE_POLICY_EXTRACTED_CONTAINER'
              value: extractedContainerName
            }
            {
              name: 'AZURE_POLICY_EXTRACTION_QUEUE_NAME'
              value: queueName
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: azureOpenAiEndpoint
            }
            {
              name: 'AZURE_OPENAI_API_KEY'
              secretRef: 'azure-openai-api-key'
            }
            {
              name: 'AZURE_OPENAI_API_VERSION'
              value: azureOpenAiApiVersion
            }
            {
              name: 'AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT'
              value: azureOpenAiEmbeddingsDeployment
            }
            {
              name: 'EMBEDDING_DIM'
              value: string(embeddingDim)
            }
            {
              name: 'EMBEDDINGS_ENABLED'
              value: 'true'
            }
            {
              name: 'EMBEDDINGS_TOP_K'
              value: '40'
            }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 15
              periodSeconds: 20
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 10
              periodSeconds: 15
            }
          ]
        }
      ]
      scale: {
        minReplicas: apiMinReplicas
        maxReplicas: apiMaxReplicas
      }
    }
  }
  dependsOn: [
    acrPullRole
  ]
}

resource workerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: workerContainerAppName
  location: location
  tags: union(tags, {
    'azd-service-name': 'worker'
    'azd-env-name': environmentName
  })
  identity: {
    type: 'SystemAssigned,UserAssigned'
    userAssignedIdentities: {
      '${acrPullIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: managedEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        {
          server: acrLoginServer
          identity: acrPullIdentity.id
        }
      ]
      secrets: [
        {
          name: 'cosmos-key'
          keyVaultUrl: '${keyVaultUri}secrets/cosmos-key'
          identity: 'system'
        }
        {
          name: 'azure-openai-api-key'
          keyVaultUrl: '${keyVaultUri}secrets/azure-openai-api-key'
          identity: 'system'
        }
        {
          name: 'storage-connection-string'
          keyVaultUrl: '${keyVaultUri}secrets/storage-connection-string'
          identity: 'system'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'policy-worker'
          image: workerImage
          env: [
            {
              name: 'ENVIRONMENT'
              value: appEnvironment
            }
            {
              name: 'DB_BACKEND'
              value: 'cosmos'
            }
            {
              name: 'COSMOS_ENDPOINT'
              value: cosmosEndpoint
            }
            {
              name: 'COSMOS_KEY'
              secretRef: 'cosmos-key'
            }
            {
              name: 'COSMOS_DATABASE'
              value: cosmosDatabase
            }
            {
              name: 'STORAGE_CONNECTION_STRING'
              secretRef: 'storage-connection-string'
            }
            {
              name: 'AZURE_STORAGE_ACCOUNT_NAME'
              value: storageAccountName
            }
            {
              name: 'AZURE_STORAGE_ACCOUNT_URL'
              value: 'https://${storageAccountName}.blob.${environment().suffixes.storage}'
            }
            {
              name: 'AZURE_STORAGE_QUEUE_ACCOUNT_URL'
              value: 'https://${storageAccountName}.queue.${environment().suffixes.storage}'
            }
            {
              name: 'AZURE_POLICY_RAW_CONTAINER'
              value: rawContainerName
            }
            {
              name: 'AZURE_POLICY_EXTRACTED_CONTAINER'
              value: extractedContainerName
            }
            {
              name: 'AZURE_POLICY_EXTRACTION_QUEUE_NAME'
              value: queueName
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: azureOpenAiEndpoint
            }
            {
              name: 'AZURE_OPENAI_API_KEY'
              secretRef: 'azure-openai-api-key'
            }
            {
              name: 'AZURE_OPENAI_API_VERSION'
              value: azureOpenAiApiVersion
            }
            {
              name: 'AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT'
              value: azureOpenAiEmbeddingsDeployment
            }
            {
              name: 'EMBEDDING_DIM'
              value: string(embeddingDim)
            }
            {
              name: 'EMBEDDINGS_ENABLED'
              value: 'true'
            }
            {
              name: 'EMBEDDINGS_TOP_K'
              value: '40'
            }
            {
              name: 'WORKER_POLL_SECONDS'
              value: '2'
            }
            {
              name: 'WORKER_VISIBILITY_TIMEOUT_SECONDS'
              value: '60'
            }
            {
              name: 'WORKER_MAX_MESSAGES'
              value: '8'
            }
          ]
        }
      ]
      scale: {
        minReplicas: workerMinReplicas
        maxReplicas: workerMaxReplicas
      }
    }
  }
  dependsOn: [
    acrPullRole
  ]
}

resource apiKeyVaultAccessRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, apiApp.id, 'kvsecretsuser')
  properties: {
    roleDefinitionId: keyVaultSecretsUserRoleDefinitionId
    principalId: apiApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource workerKeyVaultAccessRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, workerApp.id, 'kvsecretsuser')
  properties: {
    roleDefinitionId: keyVaultSecretsUserRoleDefinitionId
    principalId: workerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output apiUrl string = 'https://${apiApp.properties.configuration.ingress.fqdn}'
output apiName string = apiApp.name
output workerName string = workerApp.name
output containerAppsEnvironmentName string = managedEnvironment.name
