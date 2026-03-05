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

@description('PostgreSQL compute SKU.')
param postgresSkuName string = 'Standard_D2s_v3'

@description('PostgreSQL tier.')
@allowed([
  'Burstable'
  'GeneralPurpose'
  'MemoryOptimized'
])
param postgresSkuTier string = 'GeneralPurpose'

@description('PostgreSQL storage size in GB.')
param postgresStorageSizeGb int = 128

@description('PostgreSQL database name.')
param postgresDatabaseName string = 'policy_platform'

@description('PostgreSQL admin username; set to policy by default for app compatibility.')
param postgresAdminLogin string = 'policy'

@description('PostgreSQL admin password.')
@secure()
param postgresAdminPassword string

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

@description('Embedding vector dimension expected by schema.')
param embeddingDim int = 3072

@description('Retriever backend mode.')
param retrieverBackend string = 'hybrid'

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
var postgresServerName = toLower('pg-${take(nameSuffix, 24)}')
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

module postgres 'modules/postgres.bicep' = {
  name: 'postgresDeploy'
  params: {
    location: location
    serverName: postgresServerName
    databaseName: postgresDatabaseName
    administratorLogin: postgresAdminLogin
    administratorPassword: postgresAdminPassword
    skuName: postgresSkuName
    skuTier: postgresSkuTier
    storageSizeGb: postgresStorageSizeGb
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

resource postgresPasswordSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: '${keyVaultName}/postgres-admin-password'
  properties: {
    value: postgresAdminPassword
  }
}

resource openAiApiKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: '${keyVaultName}/azure-openai-api-key'
  properties: {
    value: azureOpenAiApiKey
  }
}

resource storageConnectionStringSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: '${keyVaultName}/storage-connection-string'
  properties: {
    value: storage.outputs.connectionString
  }
}

resource databaseUrlSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: '${keyVaultName}/database-url'
  properties: {
    value: 'postgresql+psycopg://${postgres.outputs.administratorLogin}:${postgresAdminPassword}@${postgres.outputs.host}:5432/${postgres.outputs.databaseName}?sslmode=require'
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
    retrieverBackend: retrieverBackend
  }
  dependsOn: [
    postgresPasswordSecret
    openAiApiKeySecret
    storageConnectionStringSecret
    databaseUrlSecret
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
output postgresHost string = postgres.outputs.host
output keyVaultName string = keyvault.outputs.name
output acrLoginServer string = acr.outputs.loginServer

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = acr.outputs.loginServer
output AZURE_CONTAINER_REGISTRY_NAME string = acr.outputs.name
output API_URL string = containerApps.outputs.apiUrl
output WEB_URL string = staticwebapp.outputs.webUrl
output STORAGE_ACCOUNT_NAME string = storage.outputs.name
output POSTGRES_HOST string = postgres.outputs.host
output KEY_VAULT_NAME string = keyvault.outputs.name
