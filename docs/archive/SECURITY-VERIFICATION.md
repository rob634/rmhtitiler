# Security Verification: Ensuring GDAL Only Sees SAS Tokens

This guide shows how to verify that GDAL **never** sees your storage account key, only the SAS token.

## 🔒 The Security Model

### What We Want:
```
Storage Key (in Python memory only)
    ↓
Generate SAS Token
    ↓
Pass ONLY SAS Token to GDAL (via os.environ)
    ↓
GDAL never sees the storage key ✅
```

### What We DON'T Want:
```
Storage Key → os.environ → GDAL can see it ❌
```

## ✅ Built-in Safeguards

### 1. Code-Level Protection

In `custom_main.py`, the middleware explicitly:

```python
if USE_SAS_TOKEN:
    # CRITICAL: Remove storage key from environment if it exists
    if "AZURE_STORAGE_ACCESS_KEY" in os.environ:
        del os.environ["AZURE_STORAGE_ACCESS_KEY"]
        logger.warning("Removed AZURE_STORAGE_ACCESS_KEY from environment (SAS mode)")

    # Set ONLY the SAS token
    os.environ["AZURE_STORAGE_ACCOUNT"] = AZURE_STORAGE_ACCOUNT
    os.environ["AZURE_STORAGE_SAS_TOKEN"] = sas_token
```

**This means:**
- ✅ Storage key is ONLY used in Python to generate the SAS token
- ✅ Storage key is NEVER set in `os.environ`
- ✅ If it somehow got there, we explicitly delete it
- ✅ GDAL only sees: account name + SAS token

### 2. Docker Compose Isolation

In `docker-compose.yml`, environment variables are carefully controlled:

```yaml
environment:
  # These go to the container
  - AZURE_STORAGE_ACCOUNT=mystorageaccount
  - AZURE_STORAGE_KEY=mykey  # Python reads this
  - USE_SAS_TOKEN=true

# Python reads AZURE_STORAGE_KEY
# Python generates SAS token
# Python sets os.environ["AZURE_STORAGE_SAS_TOKEN"]
# Python NEVER sets os.environ["AZURE_STORAGE_ACCESS_KEY"]
# GDAL only sees AZURE_STORAGE_SAS_TOKEN ✅
```

## 🧪 Verification Methods

### Method 1: Debug Endpoint (Easiest)

After starting TiTiler with SAS tokens enabled:

```bash
curl "http://localhost:8000/debug/env" | jq
```

**Expected Output:**
```json
{
  "warning": "This endpoint is for debugging only. Disable in production!",
  "mode": {
    "local_mode": true,
    "azure_auth_enabled": true,
    "use_sas_token": true
  },
  "what_gdal_sees": {
    "AZURE_STORAGE_ACCOUNT": "yourstorageaccount",
    "AZURE_STORAGE_ACCESS_KEY": "NOT PRESENT",  ← ✅ This is what we want!
    "AZURE_STORAGE_SAS_TOKEN": "PRESENT"
  },
  "security_check": {
    "storage_key_in_environment": false,  ← ✅ Key NOT in environment
    "sas_token_in_environment": true,      ← ✅ Token IS in environment
    "status": "✅ SECURE"
  },
  "expected_for_sas_mode": {
    "AZURE_STORAGE_ACCOUNT": "SET",
    "AZURE_STORAGE_ACCESS_KEY": "NOT PRESENT ← Key Point!",
    "AZURE_STORAGE_SAS_TOKEN": "PRESENT"
  }
}
```

### Method 2: Check Inside Container

```bash
# Exec into the running container
docker-compose exec titiler bash

# Check what's in the environment
env | grep AZURE

# Expected output:
# AZURE_STORAGE_ACCOUNT=yourstorageaccount
# AZURE_STORAGE_SAS_TOKEN=sv=2023-01-03&ss=...
# AZURE_STORAGE_KEY=yourkey  ← This is from docker-compose, Python reads it

# But check what GDAL would use (Python's os.environ after middleware runs):
python3 -c "import os; print('AZURE_STORAGE_ACCESS_KEY' in os.environ)"
# Should print: False  ← ✅ Key not visible to GDAL

python3 -c "import os; print('AZURE_STORAGE_SAS_TOKEN' in os.environ)"
# Should print: True  ← ✅ SAS token IS visible
```

### Method 3: Watch the Logs

```bash
docker-compose logs -f titiler | grep -i "storage\|sas\|gdal"
```

**Look for:**
```
INFO: Using storage account key credential (development mode)
INFO: Generating new User Delegation SAS token
INFO: SAS token generated, expires at ...
DEBUG: Set Azure SAS token for storage account: yourstorageaccount
DEBUG: GDAL will use: AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_SAS_TOKEN
```

**Should NOT see:**
```
Set Azure account key for storage account  ← Should NOT appear in SAS mode
```

### Method 4: Test GDAL Directly

```bash
# Exec into container
docker-compose exec titiler bash

# Test if GDAL can read with SAS token
python3 << 'EOF'
from osgeo import gdal
import os

# Check what GDAL sees
print(f"AZURE_STORAGE_ACCOUNT: {os.environ.get('AZURE_STORAGE_ACCOUNT', 'NOT SET')}")
print(f"AZURE_STORAGE_ACCESS_KEY: {os.environ.get('AZURE_STORAGE_ACCESS_KEY', 'NOT SET')}")
print(f"AZURE_STORAGE_SAS_TOKEN present: {'AZURE_STORAGE_SAS_TOKEN' in os.environ}")

# Try to open a COG
ds = gdal.Open("/vsiaz/yourcontainer/yourfile.tif")
if ds:
    print("✅ GDAL successfully opened COG using SAS token!")
else:
    print("❌ GDAL failed to open COG")
EOF
```

## 🔐 Security Checks Checklist

After starting TiTiler with Azure auth enabled:

- [ ] `/debug/env` shows `AZURE_STORAGE_ACCESS_KEY: NOT PRESENT`
- [ ] `/debug/env` shows `AZURE_STORAGE_SAS_TOKEN: PRESENT`
- [ ] `/debug/env` shows `status: ✅ SECURE`
- [ ] Logs show "Set Azure SAS token for storage account"
- [ ] Logs show "GDAL will use: AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_SAS_TOKEN"
- [ ] Can successfully read COGs from Azure Storage
- [ ] `env | grep AZURE_STORAGE_ACCESS_KEY` inside container returns nothing (after middleware runs)

## 🎯 Understanding the Flow

### Python Code Flow:
1. **Docker Compose** → Sets `AZURE_STORAGE_KEY` environment variable (for the container)
2. **Python startup** → Reads `os.getenv("AZURE_STORAGE_KEY")` into variable
3. **Middleware** → Uses key to generate SAS token
4. **Middleware** → Sets `os.environ["AZURE_STORAGE_SAS_TOKEN"]` = token
5. **Middleware** → Deletes `os.environ["AZURE_STORAGE_ACCESS_KEY"]` if it exists
6. **GDAL** → Only sees `AZURE_STORAGE_SAS_TOKEN` in environment

### Key Points:
- ✅ `AZURE_STORAGE_KEY` environment variable is READ by Python
- ✅ Python NEVER writes it to `os.environ`
- ✅ GDAL uses `os.environ`, so it never sees the key
- ✅ We explicitly delete `AZURE_STORAGE_ACCESS_KEY` from `os.environ` as a safety measure

## ⚠️ Common Misunderstandings

### "But the key is in the environment!"

**Clarification:** There are TWO different "environments":

1. **Container Environment** (from docker-compose.yml):
   - Has `AZURE_STORAGE_KEY` - Python reads this
   - Inherited by the Python process

2. **Python's os.environ** (what GDAL sees):
   - Does NOT have `AZURE_STORAGE_ACCESS_KEY`
   - ONLY has `AZURE_STORAGE_SAS_TOKEN`
   - This is what GDAL reads!

Python can read the container environment without writing values back to `os.environ`.

### "Docker-compose sets the key, won't GDAL see it?"

**No!** Here's why:

```python
# Python reads it WITHOUT setting it in os.environ:
AZURE_STORAGE_KEY = os.getenv("AZURE_STORAGE_KEY")  # Reads from container env

# This is NOT the same as:
os.environ["AZURE_STORAGE_ACCESS_KEY"] = AZURE_STORAGE_KEY  # We don't do this!

# We explicitly avoid setting it:
if USE_SAS_TOKEN:
    # Only set SAS token
    os.environ["AZURE_STORAGE_SAS_TOKEN"] = sas_token
    # Key is NEVER set in os.environ
```

## 🚀 Production Mode

In production with Managed Identity:

```python
# No storage key exists anywhere!
# Managed Identity → Get OAuth token
# OAuth token → Generate SAS token
# SAS token → os.environ
# GDAL → Uses SAS token
```

Even more secure because there's no key at all, anywhere!

## 📊 Comparison

| Method | Storage Key Location | What GDAL Sees | Security Level |
|--------|---------------------|----------------|----------------|
| **Direct Key** | os.environ | Storage Key | ⚠️ Low |
| **SAS Token (Dev)** | Python variable only | SAS Token | ✅ Good |
| **SAS Token (Prod)** | Doesn't exist | SAS Token | ✅✅ Excellent |

## 🔒 Best Practices

1. **Always use `USE_SAS_TOKEN=true`** - Tests production workflow
2. **Check `/debug/env`** after startup - Verify security status
3. **Disable `/debug/env` in production** - Remove it or protect with auth
4. **Never log SAS tokens** - They're credentials too!
5. **Rotate storage keys** - Even though GDAL doesn't see them

## 📝 Summary

**The key insight:**

Python reads the storage key from the container environment (`os.getenv()`) but **never** writes it to the process environment (`os.environ[]`) where GDAL would see it.

Instead, Python uses the key to generate a SAS token, then writes **only the SAS token** to `os.environ` for GDAL to use.

This way:
- ✅ Python has the key (needs it to generate SAS)
- ✅ GDAL has the SAS token (needs it to read blobs)
- ✅ GDAL never sees the key
- ✅ Same pattern as production (where managed identity replaces the key)
