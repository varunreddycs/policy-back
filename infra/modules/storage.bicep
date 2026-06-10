@description('Azure location for storage account.')
param location string

@description('Storage account name. Must be globally unique and lowercase.')
param storageAccountName string

@description('Queue used for extraction jobs.')
param queueName string = 'policy-extraction'

@description('Raw policy container name.')
param rawContainerName string = 'policy-raw'

@description('Extracted policy container name.')
param extractedContainerName string = 'policy-extracted'

@description('Resource tags to apply.')
param tags object = {}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource rawContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: rawContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource extractedContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: extractedContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource extractionQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queueService
  name: queueName
}

var accountKey = listKeys(storage.id, storage.apiVersion).keys[0].value

output id string = storage.id
output name string = storage.name
output queueName string = extractionQueue.name
output rawContainerName string = rawContainer.name
output extractedContainerName string = extractedContainer.name
output blobEndpoint string = storage.properties.primaryEndpoints.blob
output queueEndpoint string = storage.properties.primaryEndpoints.queue
output connectionString string = 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${accountKey};EndpointSuffix=${environment().suffixes.storage}'
