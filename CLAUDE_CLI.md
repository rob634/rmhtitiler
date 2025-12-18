# Claude CLI Patterns for Azure Operations

**Last Updated**: 2 December 2025  
**Purpose**: Reference for Azure CLI commands that work correctly on WBG corporate network

---

## Prerequisites

### WBG CA Certificate Bundle
The corporate network uses SSL/TLS inspection. Use the WBG CA bundle for proper certificate verification.

**CA Bundle Location**: `C:\Users\WB489446\certs\wbg-ca-bundle.pem`

See `CLI_SSL_SETUP.md` for certificate export instructions.

---

## Azure CLI via WSL

### Pattern: Standard Azure CLI Command
```bash
wsl bash -c "export REQUESTS_CA_BUNDLE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'; az <command>"
```

### Pattern: curl with SSL Certificate
```bash
wsl bash -c "export SSL_CERT_FILE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'; curl -s <url>"
```

---

## Common Commands

### Check Azure Login Status
```bash
wsl bash -c "export REQUESTS_CA_BUNDLE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'; az account show --output table"
```

### Login to Azure (Device Code)
```bash
wsl bash -c "export AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1; az login --use-device-code"
```
> ⚠️ Login requires `AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1` because login.microsoftonline.com needs additional certificates not in our bundle.

### Switch Subscription
```bash
wsl bash -c "export REQUESTS_CA_BUNDLE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'; az account set --subscription 'WBG AZ ITSOC QA PDMZ'"
```

---

## Function App Commands

### List All Settings
```bash
wsl bash -c "export REQUESTS_CA_BUNDLE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'; az functionapp config appsettings list --name fngddatahubetlqa-qa --resource-group itses-gddatahub-qa-rg -o table"
```

### Set Environment Variables
```bash
wsl bash -c "export REQUESTS_CA_BUNDLE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'; az functionapp config appsettings set --name fngddatahubetlqa-qa --resource-group itses-gddatahub-qa-rg --settings KEY1=value1 KEY2=value2 -o table"
```

### Check Function App Configuration
```bash
wsl bash -c "export REQUESTS_CA_BUNDLE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'; az functionapp config show --name fngddatahubetlqa-qa --resource-group itses-gddatahub-qa-rg -o table"
```

### Filter Settings with grep
```bash
wsl bash -c "export REQUESTS_CA_BUNDLE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'; az functionapp config appsettings list --name fngddatahubetlqa-qa --resource-group itses-gddatahub-qa-rg -o tsv 2>&1 | grep -E 'PATTERN1|PATTERN2'"
```

---

## Service Bus Commands

### List Queues
```bash
wsl bash -c "export REQUESTS_CA_BUNDLE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'; az servicebus queue list --namespace-name itses-gddatahub-sb-qa --resource-group itses-gddatahub-qa-rg -o table"
```

### Show Queue Details
```bash
wsl bash -c "export REQUESTS_CA_BUNDLE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'; az servicebus queue show --name geospatial-jobs --namespace-name itses-gddatahub-sb-qa --resource-group itses-gddatahub-qa-rg -o table"
```

---

## Azure DevOps Commands

### Show Wiki Page
```bash
wsl bash -c "export AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1; az devops wiki page show --path 'Page Name' --wiki 'ITSES-GEOSPATIAL-DEVELOPMENT-DATA-HUB.wiki' --org https://dev.azure.com/Operations-and-Corporate --project ITSES-GEOSPATIAL-DEVELOPMENT-DATA-HUB"
```

### Update Wiki Page
```bash
wsl bash -c "export AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1; az devops wiki page update --path 'Page Name' --wiki 'ITSES-GEOSPATIAL-DEVELOPMENT-DATA-HUB.wiki' --org https://dev.azure.com/Operations-and-Corporate --project ITSES-GEOSPATIAL-DEVELOPMENT-DATA-HUB --file-path '/mnt/c/path/to/content.md' --version '<eTag>'"
```

### Get Wiki Page eTag (for updates)
```bash
wsl bash -c "export AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1; az devops wiki page show --path 'Page Name' --wiki 'ITSES-GEOSPATIAL-DEVELOPMENT-DATA-HUB.wiki' --org https://dev.azure.com/Operations-and-Corporate --project ITSES-GEOSPATIAL-DEVELOPMENT-DATA-HUB --query 'eTag' -o tsv"
```

> ⚠️ Azure DevOps commands require `AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1` due to additional SSL endpoints.

---

## Testing Endpoints

### Health Check (with pretty JSON)
```bash
wsl bash -c "export SSL_CERT_FILE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'; curl -s https://fngddatahubetlqa-qa.ocappsaseqa2.appserviceenvironment.net/api/health | python3 -m json.tool"
```

### Health Check (with HTTP status)
```bash
wsl bash -c "export SSL_CERT_FILE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'; curl -s -w '\nHTTP_CODE: %{http_code}\n' https://fngddatahubetlqa-qa.ocappsaseqa2.appserviceenvironment.net/api/health"
```

### Verbose SSL Debugging
```bash
wsl bash -c "export SSL_CERT_FILE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'; curl -v https://fngddatahubetlqa-qa.ocappsaseqa2.appserviceenvironment.net/api/health 2>&1 | head -50"
```

---

## Environment Variables Reference

### SSL/TLS Variables
| Variable | Used By | Purpose |
|----------|---------|---------|
| `REQUESTS_CA_BUNDLE` | Python requests, Azure CLI | CA bundle for HTTPS verification |
| `SSL_CERT_FILE` | curl, OpenSSL | CA bundle for curl commands |
| `AZURE_CLI_DISABLE_CONNECTION_VERIFICATION` | Azure CLI | Disables SSL verification (use sparingly) |

### When to Use Each

| Scenario | Variable | Reason |
|----------|----------|--------|
| `az` commands (most) | `REQUESTS_CA_BUNDLE` | Works with WBG CA bundle |
| `az login` | `AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1` | login.microsoftonline.com needs extra certs |
| `az devops` commands | `AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1` | DevOps endpoints need extra certs |
| `curl` commands | `SSL_CERT_FILE` | curl uses this variable |

---

## QA Environment Quick Reference

| Resource | Value |
|----------|-------|
| Resource Group | `itses-gddatahub-qa-rg` |
| Function App | `fngddatahubetlqa-qa` |
| Service Bus | `itses-gddatahub-sb-qa` |
| PostgreSQL Server | `itses-gddatahub-pgsqlsvr-qa` |
| Storage Account | `itsesgddatahubqastrg` |
| Subscription | `WBG AZ ITSOC QA PDMZ` |
| ETL URL | `https://fngddatahubetlqa-qa.ocappsaseqa2.appserviceenvironment.net` |

---

## Troubleshooting

### "InsecureRequestWarning" Messages
You're using `AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1`. Switch to `REQUESTS_CA_BUNDLE` if possible.

### "SSL: CERTIFICATE_VERIFY_FAILED"
The CA bundle doesn't have the required certificate. Try `AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1` as fallback.

### "need to run login command"
WSL session lost Azure credentials. Run the login command:
```bash
wsl bash -c "export AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1; az login --use-device-code"
```

### Command Not Found in WSL
Azure CLI may not be installed in WSL. Install with:
```bash
wsl bash -c "curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash"
```
