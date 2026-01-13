# Documentation Index

**Last Updated**: November 17, 2025

This directory contains historical documentation, implementation details, and technical analysis for the TiTiler-pgSTAC project.

---

## 📋 Quick Reference

**For QA/Production Deployment** → See [../QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md) in the root directory

**For Quick Start** → See [../README.md](../README.md) in the root directory

---

## 📂 Directory Structure

### `/docs/implementation/`
**Purpose**: Detailed implementation guides and completed work

| File | Description | Status |
|------|-------------|--------|
| `IMPLEMENTATION-COMPLETE.md` | Initial implementation summary (Nov 7) | ✅ Completed |
| `POSTGRES_MI_IMPLEMENTATION.md` | PostgreSQL Managed Identity implementation | ✅ Completed |
| `PRE_DEPLOYMENT_TEST_RESULTS.md` | Docker image testing results | ✅ Passed |
| `POSTGRES-MI-SETUP.md` | Detailed PostgreSQL MI setup guide | 📚 Reference |
| `POSTGRES-ENTRA.md` | Azure Entra ID authentication patterns | 📚 Reference |
| `OAUTH-ARCHITECTURE.md` | OAuth architecture overview | 📚 Reference |

**Use When:**
- Understanding how PostgreSQL MI was implemented
- Reviewing test results before deployment
- Deep-diving into OAuth architecture

---

### `/docs/analysis/`
**Purpose**: Technical comparisons and verification reports

| File | Description | Status |
|------|-------------|--------|
| `CUSTOM_VS_DEFAULT_COMPARISON.md` | Custom vs default TiTiler analysis | 📊 Analysis |
| `verify_search_backend.md` | PostgreSQL backend verification | ✅ Verified |

**Use When:**
- Explaining customizations to stakeholders
- Understanding architectural decisions
- Verifying search storage backend

---

### `/docs/historical/`
**Purpose**: Planning documents and superseded guides

| File | Description | Status |
|------|-------------|--------|
| `TITILER-PGSTAC-BLUEPRINT.md` | Initial implementation plan (Nov 8) | 📜 Historical |
| `DEPLOYMENT.md` | Original deployment guide | 📜 Superseded by QA_DEPLOYMENT.md |
| `CONFIGURATION.md` | Initial configuration notes | 📜 Historical |
| `STAC-ETL-FIX.md` | STAC ETL integration notes | 📜 Historical |

**Use When:**
- Understanding project evolution
- Reviewing initial requirements
- Historical reference

---

## 🎯 Common Tasks

### "I need to deploy to QA/Production"
→ **[../QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md)** - Complete deployment guide

### "I need to understand PostgreSQL Managed Identity"
→ **[implementation/POSTGRES_MI_IMPLEMENTATION.md](implementation/POSTGRES_MI_IMPLEMENTATION.md)** - Implementation summary
→ **[implementation/POSTGRES-MI-SETUP.md](implementation/POSTGRES-MI-SETUP.md)** - Detailed setup guide

### "I need to explain what's custom vs standard TiTiler"
→ **[analysis/CUSTOM_VS_DEFAULT_COMPARISON.md](analysis/CUSTOM_VS_DEFAULT_COMPARISON.md)** - Complete comparison

### "I need to verify the implementation works"
→ **[implementation/PRE_DEPLOYMENT_TEST_RESULTS.md](implementation/PRE_DEPLOYMENT_TEST_RESULTS.md)** - Test results

### "I need to understand OAuth architecture"
→ **[implementation/OAUTH-ARCHITECTURE.md](implementation/OAUTH-ARCHITECTURE.md)** - OAuth flow diagrams

### "I need to see the original plan"
→ **[historical/TITILER-PGSTAC-BLUEPRINT.md](historical/TITILER-PGSTAC-BLUEPRINT.md)** - Initial blueprint

---

## 🔑 Key Concepts

### Authentication Architecture

The application uses **dual managed identity** setup:

1. **System-Assigned Managed Identity**
   - Purpose: Azure Storage OAuth
   - Role: Storage Blob Data Reader
   - Scope: Storage account level

2. **User-Assigned Managed Identity** (Optional)
   - Purpose: PostgreSQL OAuth
   - Created separately: `titiler-db-access`
   - Permissions: Read or read-write on pgSTAC

**See**: [implementation/OAUTH-ARCHITECTURE.md](implementation/OAUTH-ARCHITECTURE.md)

### Three Authentication Modes for PostgreSQL

The application supports flexible PostgreSQL authentication:

1. `managed_identity` - Passwordless (production recommended)
2. `key_vault` - Azure Key Vault for secrets
3. `password` - Environment variable (development/debugging)

**See**: [../QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md) - Part 1: Environment Variables

### Three Access Patterns

TiTiler supports multiple tile serving patterns:

1. **Direct COG** - `/cog/tiles/{z}/{x}/{y}?url=...`
2. **pgSTAC Search** - `/searches/{search_id}/tiles/{z}/{x}/{y}`
3. **MosaicJSON** - `/mosaicjson/tiles/{z}/{x}/{y}`

**See**: [../README.md](../README.md) - Usage Examples

---

## 📊 Implementation Timeline

| Date | Milestone | Document |
|------|-----------|----------|
| Nov 7, 2025 | Initial implementation complete | `implementation/IMPLEMENTATION-COMPLETE.md` |
| Nov 8, 2025 | Blueprint created | `historical/TITILER-PGSTAC-BLUEPRINT.md` |
| Nov 13, 2025 | Custom vs default analysis | `analysis/CUSTOM_VS_DEFAULT_COMPARISON.md` |
| Nov 15, 2025 | PostgreSQL MI implemented | `implementation/POSTGRES_MI_IMPLEMENTATION.md` |
| Nov 15, 2025 | Pre-deployment tests passed | `implementation/PRE_DEPLOYMENT_TEST_RESULTS.md` |
| Nov 17, 2025 | QA deployment guide created | `../QA_DEPLOYMENT.md` |
| Nov 17, 2025 | **Ready for QA migration** | 🚀 |

---

## 🚀 Current Status

**Production Status**: ✅ Ready for QA Deployment

**Live Instance**: https://geotiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net

**Current Configuration**:
- PostgreSQL: Password mode (transitioning to Managed Identity)
- Storage: System-assigned MI with Storage Blob Data Reader
- Database: Azure PostgreSQL Flexible Server with pgSTAC
- Deployment: Azure App Service with Docker container

**Next Steps**:
1. Deploy to QA environment using [../QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md)
2. ETL pipeline to handle search registration (separate Azure Function)
3. Switch to read-only PostgreSQL permissions for public-facing API

---

## 📝 Notes for QA Team

### Environment Variables Checklist
- [ ] `POSTGRES_AUTH_MODE` configured
- [ ] `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER` set
- [ ] `USE_AZURE_AUTH=true`
- [ ] `AZURE_STORAGE_ACCOUNT` set
- [ ] `LOCAL_MODE=false` for production

### RBAC Checklist
- [ ] System-assigned MI enabled on App Service
- [ ] Storage Blob Data Reader role assigned
- [ ] User-assigned MI created (if using PostgreSQL MI)
- [ ] PostgreSQL user created matching MI name

### Verification Steps
1. Health check returns `"status": "healthy"`
2. Direct COG info endpoint works
3. Tile rendering returns valid PNG
4. No 403 errors in logs

**See Full Checklist**: [../QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md) - Part 7: Production Checklist

---

## 🆘 Support

For issues or questions:
1. Check [../QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md) - Part 5: Troubleshooting
2. Review logs: `az webapp log tail --name <app-name> --resource-group <rg>`
3. Verify RBAC propagation (wait 5-10 minutes after role assignments)
4. Check health endpoint for detailed status

---

**Document Maintained By**: Claude Code
**Last Review**: November 17, 2025
**Status**: Production Ready 🚀
