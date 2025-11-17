# GitHub → Corporate Azure Workflow

**Repository**: https://github.com/rob634/rmhtitiler
**Status**: Public
**Purpose**: Bridge between development environment and corporate Azure tenant

---

## 🔄 Workflow Overview

```
Dev Mac (VS Code) → GitHub (rob634/rmhtitiler) → Work Laptop (VS Code) → Corporate ACR → Corporate Azure
```

**Key Constraint**: No direct GitHub → ACR connection. All builds happen via VS Code on work laptop.

---

## 📋 One-Time Setup

### Part 1: Dev Machine (Mac) Setup

#### 1. Check Git Remote

```bash
cd /Users/robertharrison/python_builds/titilerpgstac

# Verify remote is set
git remote -v

# Should show:
# origin  https://github.com/rob634/rmhtitiler.git (fetch)
# origin  https://github.com/rob634/rmhtitiler.git (push)
```

If not configured:
```bash
git remote add origin https://github.com/rob634/rmhtitiler.git
```

#### 2. Verify .gitignore

Ensure `.gitignore` contains:
```gitignore
# Azure CLI credentials (NEVER commit!)
.azure/

# Environment files
.env
.env.local
*.env

# Python
__pycache__/
*.pyc
*.pyo

# VS Code
.vscode/settings.json

# macOS
.DS_Store

# Docker
.docker/
```

#### 3. Test Push

```bash
# Make a test change
echo "# TiTiler-pgSTAC" >> README.md
git add README.md
git commit -m "Test commit from dev machine"
git push origin main
```

---

### Part 2: Work Laptop (Windows) Setup

#### 1. Install Prerequisites

**Git for Windows:**
```powershell
winget install Git.Git
```

**Docker Desktop:**
- Download: https://www.docker.com/products/docker-desktop
- Requires Windows 10/11 Pro, Enterprise, or Education
- Enable WSL 2 backend

**Azure CLI:**
```powershell
winget install Microsoft.AzureCLI
```

**VS Code:**
```powershell
winget install Microsoft.VisualStudioCode
```

**VS Code Extensions:**
- Docker (ms-azuretools.vscode-docker)
- Azure Account (ms-vscode.azure-account)
- Remote - WSL (ms-vscode-remote.remote-wsl)

#### 2. Clone Repository

```powershell
# Create workspace directory
mkdir C:\workspace
cd C:\workspace

# Clone repo
git clone https://github.com/rob634/rmhtitiler.git
cd rmhtitiler

# Open in VS Code
code .
```

#### 3. Configure Git

```powershell
# Set your corporate email
git config --global user.name "Your Name"
git config --global user.email "your.name@company.com"

# Verify
git config --list
```

#### 4. Azure Login

```powershell
# Login to corporate Azure tenant
az login --tenant YOUR_CORPORATE_TENANT_ID

# Verify you're in the correct subscription
az account show

# Set default subscription (if needed)
az account set --subscription "YOUR_SUBSCRIPTION_NAME"

# Login to corporate ACR
az acr login --name yourcompanyacr
```

---

## 🚀 Regular Workflow

### On Dev Machine (Mac)

#### Step 1: Make Changes

```bash
cd /Users/robertharrison/python_builds/titilerpgstac

# Edit files in VS Code
code .

# Test locally if needed
docker-compose up --build
```

#### Step 2: Commit and Push

```bash
# Check what changed
git status

# Stage changes
git add .

# Commit with descriptive message
git commit -m "Add: PostgreSQL managed identity support

- Implement three-mode authentication (MI, KeyVault, password)
- Update QA deployment documentation
- Add search registration guide for ETL"

# Push to GitHub
git push origin main
```

**Commit Message Best Practices:**
```
<type>: <short summary>

<detailed description>

<optional footer>
```

Types: `Add`, `Update`, `Fix`, `Remove`, `Refactor`, `Docs`

---

### On Work Laptop (Windows)

#### Step 1: Pull Latest Changes

Open PowerShell or Terminal in VS Code:

```powershell
cd C:\workspace\rmhtitiler

# Pull latest from GitHub
git pull origin main

# Verify what changed
git log --oneline -5
git diff HEAD~1
```

#### Step 2: Build Docker Image

**Option A: Using VS Code Docker Extension**

1. Right-click `Dockerfile` in VS Code
2. Select "Build Image..."
3. Tag: `yourcompanyacr.azurecr.io/titiler-pgstac:latest`
4. Platform: Select `linux/amd64`

**Option B: Using PowerShell**

```powershell
# Get current git commit for versioning
$GIT_SHA = git rev-parse --short HEAD
$ACR_NAME = "yourcompanyacr"
$IMAGE_NAME = "titiler-pgstac"

# Build for linux/amd64 (required for Azure App Service)
docker build --platform linux/amd64 `
  -t ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${GIT_SHA} `
  -t ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:latest `
  -f Dockerfile .

# Verify image was created
docker images | Select-String titiler-pgstac
```

#### Step 3: Push to Corporate ACR

**Option A: Using VS Code Docker Extension**

1. Open Docker extension (left sidebar)
2. Expand "Images"
3. Find your image
4. Right-click → "Push"

**Option B: Using PowerShell**

```powershell
# Ensure you're logged in
az acr login --name $ACR_NAME

# Push both tags
docker push ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${GIT_SHA}
docker push ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:latest

# Verify push
az acr repository show-tags --name $ACR_NAME --repository $IMAGE_NAME --output table
```

#### Step 4: Update App Service (Optional - if auto-deploy not configured)

```powershell
# Restart to pull latest image
az webapp restart --name your-app-name --resource-group your-rg

# Monitor logs
az webapp log tail --name your-app-name --resource-group your-rg
```

---

## 🛠️ Helper Scripts for Work Laptop

### Create `build-and-push.ps1`

Create this file in the repo root:

```powershell
# build-and-push.ps1
# Run from work laptop to build and push to corporate ACR

param(
    [string]$ACRName = "yourcompanyacr",
    [string]$ImageName = "titiler-pgstac",
    [string]$ResourceGroup = "your-rg",
    [string]$AppName = "your-app-name",
    [switch]$Deploy
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "🔄 Pulling latest changes from GitHub..." -ForegroundColor Cyan
git pull origin main

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to pull from GitHub"
    exit 1
}

# Get git commit SHA for versioning
$GitSHA = git rev-parse --short HEAD
Write-Host "📝 Git commit: $GitSHA" -ForegroundColor Green

# Build Docker image
Write-Host "🏗️  Building Docker image..." -ForegroundColor Cyan
docker build --platform linux/amd64 `
    -t "${ACRName}.azurecr.io/${ImageName}:${GitSHA}" `
    -t "${ACRName}.azurecr.io/${ImageName}:latest" `
    -f Dockerfile .

if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker build failed"
    exit 1
}

# Login to ACR
Write-Host "🔑 Logging into Azure Container Registry..." -ForegroundColor Cyan
az acr login --name $ACRName

if ($LASTEXITCODE -ne 0) {
    Write-Error "ACR login failed"
    exit 1
}

# Push to ACR
Write-Host "📦 Pushing to ACR..." -ForegroundColor Cyan
docker push "${ACRName}.azurecr.io/${ImageName}:${GitSHA}"
docker push "${ACRName}.azurecr.io/${ImageName}:latest"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker push failed"
    exit 1
}

Write-Host "✅ Image pushed successfully!" -ForegroundColor Green
Write-Host "   - ${ACRName}.azurecr.io/${ImageName}:${GitSHA}" -ForegroundColor Gray
Write-Host "   - ${ACRName}.azurecr.io/${ImageName}:latest" -ForegroundColor Gray

# Optional: Deploy to App Service
if ($Deploy) {
    Write-Host "🚀 Restarting App Service..." -ForegroundColor Cyan
    az webapp restart --name $AppName --resource-group $ResourceGroup

    Write-Host "📊 Streaming logs (Ctrl+C to stop)..." -ForegroundColor Cyan
    az webapp log tail --name $AppName --resource-group $ResourceGroup
}

Write-Host "🎉 Done!" -ForegroundColor Green
```

**Usage:**

```powershell
# Build and push only
.\build-and-push.ps1

# Build, push, and deploy
.\build-and-push.ps1 -Deploy

# Use custom ACR name
.\build-and-push.ps1 -ACRName "mycompanyacr" -Deploy
```

---

## 📊 VS Code Tasks (Advanced)

Create `.vscode/tasks.json` in the repo:

```json
{
    "version": "2.0.0",
    "tasks": [
        {
            "label": "Pull from GitHub",
            "type": "shell",
            "command": "git pull origin main",
            "problemMatcher": []
        },
        {
            "label": "Build Docker Image",
            "type": "docker-build",
            "dockerBuild": {
                "dockerfile": "${workspaceFolder}/Dockerfile",
                "context": "${workspaceFolder}",
                "tag": "yourcompanyacr.azurecr.io/titiler-pgstac:latest",
                "platform": "linux/amd64"
            }
        },
        {
            "label": "Push to ACR",
            "type": "shell",
            "command": "docker push yourcompanyacr.azurecr.io/titiler-pgstac:latest",
            "problemMatcher": []
        },
        {
            "label": "Build and Push (All)",
            "dependsOrder": "sequence",
            "dependsOn": [
                "Pull from GitHub",
                "Build Docker Image",
                "Push to ACR"
            ],
            "problemMatcher": []
        }
    ]
}
```

**Usage in VS Code:**
1. Press `Ctrl+Shift+P` (Windows) or `Cmd+Shift+P` (Mac)
2. Type "Tasks: Run Task"
3. Select "Build and Push (All)"

---

## 🔍 Verification & Troubleshooting

### On Work Laptop: Verify ACR Access

```powershell
# List repositories in ACR
az acr repository list --name yourcompanyacr --output table

# Show tags for titiler-pgstac
az acr repository show-tags `
    --name yourcompanyacr `
    --repository titiler-pgstac `
    --output table

# Test pull from ACR
docker pull yourcompanyacr.azurecr.io/titiler-pgstac:latest
```

### Common Issues

#### Issue 1: "unauthorized: authentication required"

**Solution:**
```powershell
# Re-login to Azure and ACR
az login --tenant YOUR_TENANT_ID
az acr login --name yourcompanyacr
```

#### Issue 2: "platform does not match"

**Solution:** Always include `--platform linux/amd64`:
```powershell
docker build --platform linux/amd64 -f Dockerfile .
```

#### Issue 3: "image not found" in App Service

**Solution:** Check image name matches exactly:
```powershell
# What's in ACR?
az acr repository show --name yourcompanyacr --repository titiler-pgstac

# What's App Service looking for?
az webapp config container show `
    --name your-app-name `
    --resource-group your-rg `
    --query "[linuxFxVersion, dockerRegistryServerUrl]"
```

---

## 📝 Git Best Practices

### Before Committing (Dev Machine)

```bash
# Check status
git status

# Review changes
git diff

# Test build locally
docker-compose up --build

# Stage specific files (not everything)
git add custom_pgstac_main.py
git add QA_DEPLOYMENT.md

# Commit with meaningful message
git commit -m "Update: Add managed identity configuration"
```

### Branch Strategy (Optional)

```bash
# Create feature branch for major changes
git checkout -b feature/add-keyvault-support

# Work on feature
# ... make changes ...

# Push feature branch
git push origin feature/add-keyvault-support

# Create PR on GitHub (via web UI)
# Merge after review
```

---

## 🚀 Quick Reference

### Dev Machine Workflow
```bash
cd /Users/robertharrison/python_builds/titilerpgstac
code .                          # Make changes in VS Code
git add .
git commit -m "Description"
git push origin main
```

### Work Laptop Workflow
```powershell
cd C:\workspace\rmhtitiler
git pull origin main           # Get latest changes
.\build-and-push.ps1 -Deploy   # Build, push, deploy
```

---

## 🔒 Security Checklist

- [ ] `.azure/` directory is in `.gitignore`
- [ ] No passwords or secrets in code
- [ ] No `.env` files committed
- [ ] Corporate Azure login uses correct tenant
- [ ] ACR credentials never committed to repo
- [ ] Work laptop uses corporate Azure subscription

---

## 📞 Support

**Dev Machine Issues:**
- Check: `git remote -v`
- Check: `gh auth status`
- Check: `git log --oneline -5`

**Work Laptop Issues:**
- Check: `az account show`
- Check: `az acr login --name yourcompanyacr`
- Check: `docker images | Select-String titiler`

---

**Last Updated**: November 17, 2025
**Repository**: https://github.com/rob634/rmhtitiler
**Status**: ✅ Ready for QA deployment workflow
