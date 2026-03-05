@description('Static Web App name.')
param staticWebAppName string

@description('Static Web App Azure location.')
param location string

@description('Static Web App SKU.')
@allowed([
  'Free'
  'Standard'
])
param skuName string = 'Standard'

@description('Frontend API base URL for Vite runtime config.')
param apiBaseUrl string

@description('Resource tags to apply.')
param tags object = {}

@description('azd service name tag value for SWA deployment mapping.')
param serviceName string = 'web'

resource staticSite 'Microsoft.Web/staticSites@2023-12-01' = {
  name: staticWebAppName
  location: location
  tags: union(tags, {
    'azd-service-name': serviceName
  })
  sku: {
    name: skuName
    tier: skuName
  }
  properties: {}
}

resource appSettings 'Microsoft.Web/staticSites/config@2023-12-01' = {
  name: '${staticSite.name}/appsettings'
  properties: {
    VITE_API_BASE_URL: apiBaseUrl
  }
}

output id string = staticSite.id
output name string = staticSite.name
output webUrl string = 'https://${staticSite.properties.defaultHostname}'
output defaultHostname string = staticSite.properties.defaultHostname
