@description('Azure location for Key Vault.')
param location string

@description('Key Vault name. Must be globally unique and 3-24 chars.')
param keyVaultName string

@description('Tenant ID for Key Vault.')
param tenantId string = subscription().tenantId

@description('Resource tags to apply.')
param tags object = {}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enabledForDeployment: false
    enabledForTemplateDeployment: false
    enabledForDiskEncryption: false
    publicNetworkAccess: 'Enabled'
    softDeleteRetentionInDays: 90
  }
}

output id string = vault.id
output name string = vault.name
output vaultUri string = vault.properties.vaultUri
