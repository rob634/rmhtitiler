# TiTiler Azure Documentation Index

**Last Updated:** November 7, 2025
**Project Status:** ✅ Production Deployed

---

## 📚 Documentation Structure

### **Quick Start**

| Document | Purpose | Audience |
|----------|---------|----------|
| [README.md](README.md) | Main project overview and quick start | Everyone |
| [README-LOCAL.md](README-LOCAL.md) | Local development setup and testing | Developers |

### **Production Deployment**

| Document | Purpose | Audience |
|----------|---------|----------|
| [DEPLOYMENT-TROUBLESHOOTING.md](DEPLOYMENT-TROUBLESHOOTING.md) | Production deployment details and issue resolutions | DevOps, IT |
| [AZURE-CONFIGURATION-REFERENCE.md](AZURE-CONFIGURATION-REFERENCE.md) | Corporate IT service request documentation | IT Department |

### **API Reference & Integration**

| Document | Purpose | Audience |
|----------|---------|----------|
| [TITILER-API-REFERENCE.md](TITILER-API-REFERENCE.md) | Complete API documentation with code examples | ETL Pipeline Team |
| [STAC-INTEGRATION-GUIDE.md](STAC-INTEGRATION-GUIDE.md) | Quick start guide for STAC catalog integration | ETL Pipeline Team |

### **Architecture & Design**

| Document | Purpose | Audience |
|----------|---------|----------|
| [design.md](design.md) | Detailed architecture and design decisions | Developers, Architects |

---

## 🗂️ Archived Documentation

The following documents were archived on **November 7, 2025** after successful production deployment:

### Archived to `docs/archive/`

| Document | Original Purpose | Archive Reason |
|----------|-----------------|----------------|
| [AUTHENTICATION-VERIFICATION.md](docs/archive/AUTHENTICATION-VERIFICATION.md) | Debug logs proving dynamic SAS token generation | Development artifact - purpose achieved |
| [SAS-TOKEN-TESTING.md](docs/archive/SAS-TOKEN-TESTING.md) | Local SAS token testing guide | Superseded by README-LOCAL.md |
| [SECURITY-VERIFICATION.md](docs/archive/SECURITY-VERIFICATION.md) | Security testing and verification guide | Security model proven and documented |
| [TESTING-COMPLETE.md](docs/archive/TESTING-COMPLETE.md) | Testing completion report (Nov 7, 2025) | Historical snapshot - testing complete |
| [AZURE-DEPLOYMENT-PREP.md](docs/archive/AZURE-DEPLOYMENT-PREP.md) | Pre-deployment preparation checklist | Deployment complete - details in DEPLOYMENT-TROUBLESHOOTING.md |

**Note:** Archived documents are preserved for historical reference but are no longer maintained.

---

## 📖 Documentation Overview

### Current Production Setup

**Environment:** Azure App Service
**Endpoint:** https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net
**Container Registry:** rmhazureacr.azurecr.io
**Image:** titiler-azure:v1.0.2
**Storage:** rmhazuregeo/silver-cogs
**Authentication:** Managed Identity + User Delegation SAS tokens

### Key Features Documented

- ✅ Azure Managed Identity authentication
- ✅ User Delegation SAS token generation
- ✅ Local development with Docker Compose
- ✅ Production deployment to Azure App Service
- ✅ STAC catalog integration
- ✅ Complete API reference
- ✅ Troubleshooting guides

---

## 🚀 Common Tasks - Quick Links

### For Developers

- **Start local development:** [README-LOCAL.md](README-LOCAL.md#quick-start)
- **Understand architecture:** [design.md](design.md#architecture)
- **Debug authentication issues:** [DEPLOYMENT-TROUBLESHOOTING.md](DEPLOYMENT-TROUBLESHOOTING.md#troubleshooting)

### For ETL Pipeline Integration

- **Quick start guide:** [STAC-INTEGRATION-GUIDE.md](STAC-INTEGRATION-GUIDE.md)
- **Full API reference:** [TITILER-API-REFERENCE.md](TITILER-API-REFERENCE.md)
- **Python code examples:** [TITILER-API-REFERENCE.md#python-code-examples](TITILER-API-REFERENCE.md#python-code-examples-for-stac-catalog-integration)

### For IT/DevOps

- **Deployment troubleshooting:** [DEPLOYMENT-TROUBLESHOOTING.md](DEPLOYMENT-TROUBLESHOOTING.md)
- **Azure configuration:** [AZURE-CONFIGURATION-REFERENCE.md](AZURE-CONFIGURATION-REFERENCE.md)
- **Service requests:** [AZURE-CONFIGURATION-REFERENCE.md](AZURE-CONFIGURATION-REFERENCE.md)

---

## 🔍 Finding Information

### "How do I..."

| Question | Document | Section |
|----------|----------|---------|
| Set up local development? | [README-LOCAL.md](README-LOCAL.md) | Quick Start |
| Use the TiTiler API? | [TITILER-API-REFERENCE.md](TITILER-API-REFERENCE.md) | All sections |
| Integrate with STAC? | [STAC-INTEGRATION-GUIDE.md](STAC-INTEGRATION-GUIDE.md) | Python Integration |
| Deploy to Azure? | [DEPLOYMENT-TROUBLESHOOTING.md](DEPLOYMENT-TROUBLESHOOTING.md) | Resolution Summary |
| Request corporate IT changes? | [AZURE-CONFIGURATION-REFERENCE.md](AZURE-CONFIGURATION-REFERENCE.md) | Service Requests |
| Understand the architecture? | [design.md](design.md) | Architecture |
| Fix authentication errors? | [DEPLOYMENT-TROUBLESHOOTING.md](DEPLOYMENT-TROUBLESHOOTING.md) | Issues Found and Fixed |

---

## 📊 Documentation Statistics

**Total Active Documents:** 7
**Total Archived Documents:** 5
**Total Lines (Active):** ~3,200 lines
**Total Size (Active):** ~100KB

### Active Documentation by Category

- **Getting Started:** 2 docs (README.md, README-LOCAL.md)
- **Deployment:** 2 docs (DEPLOYMENT-TROUBLESHOOTING.md, AZURE-CONFIGURATION-REFERENCE.md)
- **API/Integration:** 2 docs (TITILER-API-REFERENCE.md, STAC-INTEGRATION-GUIDE.md)
- **Architecture:** 1 doc (design.md)

---

## 📝 Maintenance Notes

### When to Update Documentation

- **README.md:** Changes to features, setup, or main usage
- **README-LOCAL.md:** Changes to local development workflow
- **TITILER-API-REFERENCE.md:** API endpoint changes or new features
- **STAC-INTEGRATION-GUIDE.md:** Changes to STAC integration patterns
- **DEPLOYMENT-TROUBLESHOOTING.md:** New deployment issues or fixes
- **design.md:** Architectural changes or design decisions

### Document Ownership

- **Development Docs:** Development Team
- **Deployment Docs:** DevOps Team
- **API Docs:** API Team / ETL Pipeline Team
- **Architecture Docs:** Architecture Team

---

## 🔗 External Resources

- [TiTiler Documentation](https://developmentseed.org/titiler/)
- [Azure Managed Identities](https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/overview)
- [GDAL Virtual File Systems](https://gdal.org/user/virtual_file_systems.html#vsiaz-microsoft-azure-blob-files)
- [STAC Specification](https://stacspec.org/)

---

**Questions or Issues?** See [DEPLOYMENT-TROUBLESHOOTING.md](DEPLOYMENT-TROUBLESHOOTING.md) or check the [GitHub repository](https://github.com/developmentseed/titiler).
