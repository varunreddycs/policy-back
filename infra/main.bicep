targetScope = 'resourceGroup'

@description('Azure location for all resources.')
param location string = resourceGroup().location

@description('Short environment name used in tags and resource names (e.g. dev, prod).')
param environmentName string = 'dev'

@description('Optional resource group name hint for documentation/traceability.')
param resourceGroupName string = ''

@description('Additional tags applied to all resources.')
param tags object = {}

@description('ACR SKU tier.')
@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param acrSku string = 'Basic'

@description('Static Web App SKU tier.')
@allowed([
  'Free'
  'Standard'
])
param staticWebAppSku string = 'Standard'

@description('Azure Cosmos DB NoSQL account endpoint.')
param cosmosEndpoint string

@description('Azure Cosmos DB NoSQL account key.')
@secure()
param cosmosKey string

@description('Cosmos DB database name.')
param cosmosDatabase string = 'policydb'

@description('Azure OpenAI endpoint URL.')
param azureOpenAiEndpoint string = ''

@description('Azure OpenAI API version.')
param azureOpenAiApiVersion string = '2024-02-15-preview'

@description('Azure OpenAI embeddings deployment name.')
param azureOpenAiEmbeddingsDeployment string = ''

@description('Azure OpenAI API key.')
@secure()
param azureOpenAiApiKey string

@description('Image tag for API container image.')
param apiImageTag string = 'latest'

@description('Image tag for worker container image.')
param workerImageTag string = 'latest'

@description('API minimum replicas.')
param apiMinReplicas int = 1

@description('API maximum replicas.')
param apiMaxReplicas int = 3

@description('Worker minimum replicas.')
param workerMinReplicas int = 1

@description('Worker maximum replicas.')
param workerMaxReplicas int = 2

@description('Raw blob container name.')
param rawBlobContainerName string = 'policy-raw'

@description('Extracted blob container name.')
param extractedBlobContainerName string = 'policy-extracted'

@description('Queue name for extraction jobs.')
param queueName string = 'policy-extraction'

@description('Embedding vector dimension.')
param embeddingDim int = 3072

@description('Enable FastAPI /docs in deployed API.')
param enableApiDocs bool = false

@description('Runtime environment label provided to app code.')
param appEnvironment string = 'cloud'

var nameSuffix = toLower(uniqueString(subscription().subscriptionId, resourceGroup().id, environmentName))
var shortEnv = toLower(take(replace(environmentName, '-', ''), 8))

var mergedTags = union(tags, {
  'azd-env-name': environmentName
  environment: environmentName
  'resource-group-hint': empty(resourceGroupName) ? resourceGroup().name : resourceGroupName
  workload: 'policy-platform'
})

var acrName = toLower('acr${take(nameSuffix, 18)}')
var storageAccountName = toLower('st${take(nameSuffix, 22)}')
var keyVaultName = toLower('kv-${take(nameSuffix, 21)}')
var containerAppsEnvironmentName = toLower('cae-${shortEnv}-${take(nameSuffix, 8)}')
var apiContainerAppName = toLower('policy-api-${shortEnv}')
var workerContainerAppName = toLower('policy-worker-${shortEnv}')
var staticWebAppName = toLower('policy-web-${shortEnv}-${take(nameSuffix, 6)}')

module acr 'modules/acr.bicep' = {
  name: 'acrDeploy'
  params: {
    location: location
    registryName: acrName
    skuName: acrSku
    tags: mergedTags
  }
}

module storage 'modules/storage.bicep' = {
  name: 'storageDeploy'
  params: {
    location: location
    storageAccountName: storageAccountName
    queueName: queueName
    rawContainerName: rawBlobContainerName
    extractedContainerName: extractedBlobContainerName
    tags: mergedTags
  }
}

module keyvault 'modules/keyvault.bicep' = {
  name: 'keyVaultDeploy'
  params: {
    location: location
    keyVaultName: keyVaultName
    tags: mergedTags
  }
}

resource cosmosKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: '${keyVaultName}/cosmos-key'
  dependsOn: [keyvault]
  properties: {
    value: cosmosKey
  }
}

resource openAiApiKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: '${keyVaultName}/azure-openai-api-key'
  dependsOn: [keyvault]
  properties: {
    value: azureOpenAiApiKey
  }
}

resource storageConnectionStringSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: '${keyVaultName}/storage-connection-string'
  dependsOn: [keyvault]
  properties: {
    value: storage.outputs.connectionString
  }
}

module containerApps 'modules/containerapps.bicep' = {
  name: 'containerAppsDeploy'
  params: {
    location: location
    environmentName: environmentName
    tags: mergedTags
    containerAppsEnvironmentName: containerAppsEnvironmentName
    apiContainerAppName: apiContainerAppName
    workerContainerAppName: workerContainerAppName
    apiImage: '${acr.outputs.loginServer}/policy-api:${apiImageTag}'
    workerImage: '${acr.outputs.loginServer}/policy-worker:${workerImageTag}'
    acrLoginServer: acr.outputs.loginServer
    acrName: acrName
    keyVaultUri: keyvault.outputs.vaultUri
    keyVaultName: keyVaultName
    storageAccountName: storage.outputs.name
    rawContainerName: storage.outputs.rawContainerName
    extractedContainerName: storage.outputs.extractedContainerName
    queueName: storage.outputs.queueName
    cosmosEndpoint: cosmosEndpoint
    cosmosDatabase: cosmosDatabase
    azureOpenAiEndpoint: azureOpenAiEndpoint
    azureOpenAiApiVersion: azureOpenAiApiVersion
    azureOpenAiEmbeddingsDeployment: azureOpenAiEmbeddingsDeployment
    appEnvironment: appEnvironment
    enableDocs: enableApiDocs
    apiMinReplicas: apiMinReplicas
    apiMaxReplicas: apiMaxReplicas
    workerMinReplicas: workerMinReplicas
    workerMaxReplicas: workerMaxReplicas
    embeddingDim: embeddingDim
  }
  dependsOn: [
    cosmosKeySecret
    openAiApiKeySecret
    storageConnectionStringSecret
  ]
}

module staticwebapp 'modules/staticwebapp.bicep' = {
  name: 'staticWebAppDeploy'
  params: {
    location: location
    staticWebAppName: staticWebAppName
    skuName: staticWebAppSku
    apiBaseUrl: containerApps.outputs.apiUrl
    tags: mergedTags
    serviceName: 'web'
  }
}

output apiUrl string = containerApps.outputs.apiUrl
output webUrl string = staticwebapp.outputs.webUrl
output storageAccountName string = storage.outputs.name
output queueName string = storage.outputs.queueName
output keyVaultName string = keyvault.outputs.name
output acrLoginServer string = acr.outputs.loginServer

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = acr.outputs.loginServer
output AZURE_CONTAINER_REGISTRY_NAME string = acr.outputs.name
output API_URL string = containerApps.outputs.apiUrl
output WEB_URL string = staticwebapp.outputs.webUrl
output STORAGE_ACCOUNT_NAME string = storage.outputs.name
output KEY_VAULT_NAME string = keyvault.outputs.name
