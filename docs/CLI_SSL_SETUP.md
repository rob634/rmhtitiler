# CLI SSL Setup for Corporate Proxy Environment

**Date**: December 2, 2025  
**Environment**: World Bank Group Corporate Network  
**Problem**: Azure CLI and Python tools fail with SSL certificate errors behind corporate proxy

---

## 🔍 The Problem

When using Azure CLI (`az`) or Python-based tools behind the WBG corporate network, you may encounter:

```
ERROR: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain
```

### Why This Happens

The corporate network uses **SSL/TLS inspection** (MITM) via security tools like Zscaler or Palo Alto. The proxy intercepts HTTPS traffic and re-signs it with a corporate certificate.

| Tool | Trust Store | Result |
|------|-------------|--------|
| **Web Browser** | Windows Certificate Store | ✅ Works (has corporate CA) |
| **Azure CLI (Python)** | `certifi` CA bundle | ❌ Fails (missing corporate CA) |
| **WSL/Linux tools** | Linux CA store | ❌ Fails (missing corporate CA) |

---

## 🛠️ The Solution

Export the WBG root CA certificates and configure Python/Azure CLI to trust them.

---

## Step 1: Identify Corporate Root CA Certificates

Run this PowerShell command to find WBG certificates in the Windows trust store:

```powershell
Get-ChildItem Cert:\LocalMachine\Root | Where-Object { 
    $_.Issuer -like "*World*" -or $_.Issuer -like "*WBG*" 
} | Select-Object Subject, Issuer, Thumbprint, NotAfter | Format-Table -AutoSize
```

**Expected Output:**
```
Subject                                        Issuer                                         Thumbprint                               NotAfter
-------                                        ------                                         ----------                               --------
CN=WBG Root CA G2, O=World Bank Group, C=US    CN=WBG Root CA G2, O=World Bank Group, C=US    17CFD8B332A8D9783F14CC6E39F7B4A87849831E 4/21/2036
CN=WBG Cloud Root CA, O=World Bank Group, C=US CN=WBG Cloud Root CA, O=World Bank Group, C=US 08FFB921F9E2188B0F293EB54B68F9B4F8DF13A4 4/27/2043
```

---

## Step 2: Create Certificate Directory

```powershell
$certDir = "$env:USERPROFILE\certs"
New-Item -ItemType Directory -Path $certDir -Force
```

This creates: `C:\Users\<username>\certs\`

---

## Step 3: Export Certificates in DER Format

```powershell
$certDir = "$env:USERPROFILE\certs"

Get-ChildItem Cert:\LocalMachine\Root | Where-Object { 
    $_.Issuer -like "*World Bank*" -or $_.Issuer -like "*WBG*" 
} | ForEach-Object { 
    $certPath = "$certDir\$($_.Thumbprint).cer"
    Export-Certificate -Cert $_ -FilePath $certPath -Type CERT | Out-Null
    Write-Host "Exported: $certPath"
}
```

**Files Created:**
- `C:\Users\<username>\certs\17CFD8B332A8D9783F14CC6E39F7B4A87849831E.cer` (WBG Root CA G2)
- `C:\Users\<username>\certs\08FFB921F9E2188B0F293EB54B68F9B4F8DF13A4.cer` (WBG Cloud Root CA)

---

## Step 4: Convert to PEM Format

Azure CLI and Python require PEM format. Use `certutil` to convert:

```powershell
$certDir = "$env:USERPROFILE\certs"

Get-ChildItem "$certDir\*.cer" | ForEach-Object { 
    $pemFile = $_.FullName -replace '\.cer$','.pem'
    certutil -encode $_.FullName $pemFile | Out-Null
    Write-Host "Converted: $pemFile"
}
```

**Files Created:**
- `C:\Users\<username>\certs\17CFD8B332A8D9783F14CC6E39F7B4A87849831E.pem`
- `C:\Users\<username>\certs\08FFB921F9E2188B0F293EB54B68F9B4F8DF13A4.pem`

---

## Step 5: Create Combined CA Bundle

Combine all PEM certificates into a single bundle file:

```powershell
$certDir = "$env:USERPROFILE\certs"
$bundle = "$certDir\wbg-ca-bundle.pem"

# Combine all PEM files
Get-ChildItem "$certDir\*.pem" | Where-Object { $_.Name -ne "wbg-ca-bundle.pem" } | ForEach-Object {
    Get-Content $_.FullName | Add-Content $bundle
}

Write-Host "Created bundle: $bundle"
```

**Final Bundle:** `C:\Users\<username>\certs\wbg-ca-bundle.pem`

### Verify Bundle Contents

```powershell
Get-Content "$env:USERPROFILE\certs\wbg-ca-bundle.pem"
```

Should show multiple `-----BEGIN CERTIFICATE-----` blocks.

---

## Step 6: Configure Azure CLI to Use the Bundle

### Option A: Environment Variable (Recommended)

**For WSL/Bash:**
```bash
export REQUESTS_CA_BUNDLE='/mnt/c/Users/<username>/certs/wbg-ca-bundle.pem'
```

**For PowerShell:**
```powershell
$env:REQUESTS_CA_BUNDLE = "$env:USERPROFILE\certs\wbg-ca-bundle.pem"
```

### Option B: Permanent Configuration

**Add to WSL `~/.bashrc`:**
```bash
echo 'export REQUESTS_CA_BUNDLE="/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem"' >> ~/.bashrc
source ~/.bashrc
```

**Add to PowerShell Profile:**
```powershell
Add-Content $PROFILE '$env:REQUESTS_CA_BUNDLE = "$env:USERPROFILE\certs\wbg-ca-bundle.pem"'
```

---

## 📋 Usage Examples

### Azure CLI via WSL (Correct Way)

```bash
# Set the CA bundle
export REQUESTS_CA_BUNDLE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'

# Now az cli works without SSL errors
az functionapp config appsettings list \
    --name fngddatahubintqa-qa \
    --resource-group itses-gddatahub-qa-rg \
    --output table
```

### One-Liner for WSL Commands from PowerShell

```powershell
wsl bash -c "export REQUESTS_CA_BUNDLE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'; az functionapp list --output table"
```

### Application Insights Query

```bash
export REQUESTS_CA_BUNDLE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'

az monitor app-insights query \
    --app 'itses-gddatahub-qa' \
    --resource-group itses-gddatahub-qa-rg \
    --analytics-query 'exceptions | where timestamp > ago(1h) | take 10'
```

---

## ⚠️ Alternative: Disable SSL Verification (NOT Recommended)

If you cannot set up the CA bundle, you can disable verification as a temporary workaround:

```bash
export AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1
az functionapp list --output table
```

**Warnings:**
- ❌ Less secure - vulnerable to MITM attacks
- ❌ Shows `InsecureRequestWarning` on every request
- ❌ Some Azure SDK operations may still fail
- ❌ Application Insights queries fail even with this setting

**Use only when the proper CA bundle setup isn't possible.**

---

## 🔧 Troubleshooting

### Issue: "Permission Denied" when creating certs folder

Use your home directory instead of `C:\certs`:
```powershell
$certDir = "$env:USERPROFILE\certs"
```

### Issue: PowerShell "Constrained Language Mode" errors

Corporate security may restrict PowerShell operations. Use `certutil` instead of .NET methods:
```powershell
certutil -encode input.cer output.pem
```

### Issue: WSL can't find the certificate file

Ensure you're using the correct WSL path format:
```bash
# Windows path: C:\Users\WB489446\certs\wbg-ca-bundle.pem
# WSL path:     /mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem
```

### Issue: Certificate expired

Re-run Step 1 to check certificate expiration dates. WBG certificates are valid until 2036-2043.

---

## 📁 File Locations Summary

| File | Path | Purpose |
|------|------|---------|
| WBG Root CA G2 (DER) | `C:\Users\<username>\certs\17CFD8B332A8D9783F14CC6E39F7B4A87849831E.cer` | Original export |
| WBG Cloud Root CA (DER) | `C:\Users\<username>\certs\08FFB921F9E2188B0F293EB54B68F9B4F8DF13A4.cer` | Original export |
| WBG Root CA G2 (PEM) | `C:\Users\<username>\certs\17CFD8B332A8D9783F14CC6E39F7B4A87849831E.pem` | Converted format |
| WBG Cloud Root CA (PEM) | `C:\Users\<username>\certs\08FFB921F9E2188B0F293EB54B68F9B4F8DF13A4.pem` | Converted format |
| **Combined Bundle** | `C:\Users\<username>\certs\wbg-ca-bundle.pem` | **Use this one** |

---

## 🔐 Security Notes

1. **This is the secure approach** - we're adding trust for legitimate corporate certificates, not disabling security
2. **Certificates are organization-specific** - these WBG certificates won't work outside the World Bank network
3. **Keep certificates updated** - if IT rotates root CAs, re-export the new ones
4. **Don't share certificate files** - while not secret, they're specific to your organization

---

## ✅ Verification

After setup, test that SSL works without warnings:

```bash
export REQUESTS_CA_BUNDLE='/mnt/c/Users/WB489446/certs/wbg-ca-bundle.pem'

# This should work WITHOUT any SSL warnings
az account show --output table
```

If you see output without `InsecureRequestWarning`, the setup is complete!

---

## 📚 References

- [Azure CLI: Work behind a proxy](https://learn.microsoft.com/cli/azure/use-cli-effectively#work-behind-a-proxy)
- [Python Requests: SSL Cert Verification](https://requests.readthedocs.io/en/latest/user/advanced/#ssl-cert-verification)
- [certifi: Custom CA Bundles](https://pypi.org/project/certifi/)
