@description('Azure location for ACR.')
param location string

@description('Container registry name. Must be globally unique and lowercase.')
param registryName string

@description('Resource tags to apply.')
param tags object = {}

@description('ACR SKU tier.')
@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param skuName string = 'Basic'

resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: registryName
  location: location
  sku: {
    name: skuName
  }
  tags: tags
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

output id string = registry.id
output name string = registry.name
output loginServer string = registry.properties.loginServer
