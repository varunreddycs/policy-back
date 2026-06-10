@description('Azure location for PostgreSQL flexible server.')
param location string

@description('PostgreSQL flexible server name. Must be globally unique.')
param serverName string

@description('PostgreSQL database name.')
param databaseName string = 'policy_platform'

@description('PostgreSQL admin username.')
param administratorLogin string = 'policyadmin'

@description('PostgreSQL admin password.')
@secure()
param administratorPassword string

@description('PostgreSQL version.')
@allowed([
  '15'
  '16'
])
param version string = '16'

@description('Compute SKU for PostgreSQL flexible server.')
param skuName string = 'Standard_D2s_v3'

@description('Tier for PostgreSQL flexible server SKU.')
@allowed([
  'Burstable'
  'GeneralPurpose'
  'MemoryOptimized'
])
param skuTier string = 'GeneralPurpose'

@description('Storage size in GB.')
param storageSizeGb int = 128

@description('Resource tags to apply.')
param tags object = {}

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: serverName
  location: location
  tags: tags
  sku: {
    name: skuName
    tier: skuTier
  }
  properties: {
    createMode: 'Default'
    version: version
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorPassword
    authConfig: {
      activeDirectoryAuth: 'Disabled'
      passwordAuth: 'Enabled'
    }
    network: {
      publicNetworkAccess: 'Enabled'
    }
    storage: {
      storageSizeGB: storageSizeGb
    }
    highAvailability: {
      mode: 'Disabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
  }
}

resource allowAzureServices 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-06-01-preview' = {
  parent: server
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource db 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = {
  parent: server
  name: databaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource azureExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2023-06-01-preview' = {
  parent: server
  name: 'azure.extensions'
  properties: {
    value: 'VECTOR,PGCRYPTO'
    source: 'user-override'
  }
}

output id string = server.id
output name string = server.name
output host string = server.properties.fullyQualifiedDomainName
output databaseName string = db.name
output administratorLogin string = administratorLogin
