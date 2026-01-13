# TiTiler Azure Authentication Roadmap

**Last Updated**: November 7, 2025
**Status**: Active Development

---

## Current Status

### Completed (v1.0.2) ✅
- [x] TiTiler with Azure Managed Identity deployed to production
- [x] User Delegation SAS token authentication working
- [x] Container-scoped access (silver-cogs container)
- [x] Comprehensive documentation suite
- [x] CLAUDE.md documenting AI collaboration
- [x] GitHub repository created and published
- [x] All endpoints verified working (info, statistics, tiles, viewer, preview)

### Critical Insight (November 7, 2025) 💡
- [x] Discovered OAuth token approach is simpler and better than SAS tokens
- [x] OAuth tokens solve multi-container problem automatically
- [x] Documented in [OAUTH-TOKEN-APPROACH.md](OAUTH-TOKEN-APPROACH.md)
- [x] Documented TiTiler-pgSTAC strategy in [PGSTAC-IMPLEMENTATION.md](PGSTAC-IMPLEMENTATION.md)

---

## Phase 1: Refactor TiTiler to OAuth Tokens

**Objective**: Replace SAS token implementation with OAuth tokens for simplicity and multi-container support

**Priority**: HIGH
**Timeline**: 1-2 hours
**Status**: 🟡 Ready to Start

### Tasks

#### 1.1 Code Refactoring
- [ ] Read current `custom_main.py` to understand SAS implementation
- [ ] Create `custom_main_oauth.py` with OAuth approach
- [ ] Replace SAS generation code with OAuth token acquisition
- [ ] Update environment variable from `AZURE_STORAGE_SAS_TOKEN` to `AZURE_STORAGE_ACCESS_TOKEN`
- [ ] Simplify token caching logic (fewer fields needed)
- [ ] Update health check endpoint to show OAuth token status
- [ ] Update logging to indicate OAuth vs SAS mode

**Key Changes**:
```python
# Remove
from azure.storage.blob import BlobServiceClient, generate_container_sas

# Replace with
from azure.identity import DefaultAzureCredential

# Old function (~150 lines)
def generate_user_delegation_sas(): ...

# New function (~30 lines)
def get_azure_storage_oauth_token():
    credential = DefaultAzureCredential()
    token = credential.get_token("https://storage.azure.com/.default")
    return token.token
```

#### 1.2 Local Testing
- [ ] Test OAuth token acquisition locally with `az login`
- [ ] Verify GDAL can read from multiple containers with one token
- [ ] Test token refresh logic
- [ ] Verify all TiTiler endpoints work with OAuth tokens
- [ ] Compare performance: SAS vs OAuth token generation

**Test Script**:
```bash
# Test multiple containers with OAuth
python test_oauth_multi_container.py

# Expected: Single token works for all containers
```

#### 1.3 Documentation Updates
- [ ] Update README.md to mention OAuth approach
- [ ] Update [design.md](design.md) architecture section
- [ ] Update [DEPLOYMENT-TROUBLESHOOTING.md](DEPLOYMENT-TROUBLESHOOTING.md)
- [ ] Create migration guide from SAS to OAuth
- [ ] Update CLAUDE.md with OAuth refactoring details

#### 1.4 Production Deployment (v2.0.0)
- [ ] Update `custom_main.py` with OAuth implementation
- [ ] Remove `AZURE_CONTAINER` environment variable (no longer needed)
- [ ] Keep `USE_SAS_TOKEN=false` or remove variable entirely
- [ ] Build new Docker image: `geotiler:2.0.0-oauth`
- [ ] Deploy to Azure App Service
- [ ] Verify all endpoints work
- [ ] Test access to multiple containers (if available)
- [ ] Monitor logs for OAuth token acquisition
- [ ] Verify token refresh behavior

**Deployment Commands**:
```bash
# Build with new OAuth implementation
az acr build --registry rmhacr --image geotiler:2.0.0-oauth .

# Update App Service
az webapp config container set \
  --name geotiler-ghcyd7g0bxdvc2hc \
  --resource-group rmhgeography \
  --docker-custom-image-name rmhacr.azurecr.io/geotiler:2.0.0-oauth

# Monitor deployment
az webapp log tail --name geotiler-ghcyd7g0bxdvc2hc --resource-group rmhgeography
```

#### 1.5 Validation
- [ ] Verify OAuth token shown in /healthz endpoint
- [ ] Test COG access from original container (silver-cogs)
- [ ] Test COG access from additional containers (if available)
- [ ] Verify token expiry and refresh
- [ ] Performance benchmark: token generation time
- [ ] Confirm RBAC permissions are respected

**Success Criteria**:
- ✅ All endpoints return 200 OK
- ✅ OAuth token visible in logs and /healthz
- ✅ Single token works for multiple containers
- ✅ Code reduced by ~150 lines
- ✅ No `azure-storage-blob` dependency needed

---

## Phase 2: TiTiler-pgSTAC Implementation

**Objective**: Create new TiTiler-pgSTAC project with OAuth authentication for STAC catalog integration

**Priority**: MEDIUM
**Timeline**: 3-5 days
**Status**: 🔴 Blocked by Phase 1
**Depends On**: Phase 1 completion

### Prerequisites
- [ ] Phase 1 completed and validated
- [ ] OAuth approach proven in production TiTiler
- [ ] Azure Database for PostgreSQL Flexible Server available
- [ ] pgSTAC extension installed in PostgreSQL
- [ ] Sample STAC data ingested

### Tasks

#### 2.1 Project Setup
- [ ] Create new project directory: `geotiler-pgstac/`
- [ ] Copy OAuth authentication code from Phase 1
- [ ] Create Dockerfile based on `ghcr.io/stac-utils/titiler-pgstac:latest`
- [ ] Add PostgreSQL connection dependencies (`asyncpg`, `psycopg2`)
- [ ] Create docker-compose.yml for local development with PostgreSQL
- [ ] Set up environment variables (DATABASE_URL, AZURE_STORAGE_ACCOUNT)

**Directory Structure**:
```
geotiler-pgstac/
├── custom_pgstac_main.py     # Main application (OAuth auth + pgSTAC)
├── Dockerfile                 # Production image
├── Dockerfile.local           # Local development
├── docker-compose.yml         # Local: TiTiler-pgSTAC + PostgreSQL
├── requirements.txt           # Production dependencies
├── requirements-local.txt     # Local development dependencies
├── .env.local.example         # Example environment variables
└── README.md                  # Project documentation
```

#### 2.2 Authentication Integration
- [ ] Copy OAuth token generation code from Phase 1
- [ ] Adapt middleware for TiTiler-pgSTAC request flow
- [ ] Ensure OAuth token set before STAC item asset access
- [ ] Test with STAC items referencing multiple containers
- [ ] Verify GDAL can access all asset URLs

#### 2.3 pgSTAC Integration
- [ ] Set up PostgreSQL connection pool
- [ ] Configure TiTiler-pgSTAC factory with custom settings
- [ ] Create mosaic endpoints for STAC searches
- [ ] Implement STAC item search → tile generation flow
- [ ] Test dynamic mosaics from search queries

#### 2.4 Testing
- [ ] Unit tests: OAuth token generation
- [ ] Unit tests: Database connection
- [ ] Integration tests: STAC search → tile generation
- [ ] Integration tests: Multi-container asset access
- [ ] Performance tests: Mosaic generation from 10+ items
- [ ] End-to-end tests: Search → extract URLs → generate tiles

**Test Scenarios**:
```python
# Test 1: Single STAC item from one container
# Test 2: Mosaic from items in multiple containers
# Test 3: Large search result (100+ items)
# Test 4: Token refresh during long-running operation
```

#### 2.5 Documentation
- [ ] Create comprehensive README.md
- [ ] Document DATABASE_URL configuration
- [ ] Create STAC data ingestion guide
- [ ] Document API endpoints (search, mosaic, tiles)
- [ ] Create local development guide
- [ ] Update PGSTAC-IMPLEMENTATION.md with actual implementation details

#### 2.6 Production Deployment
- [ ] Build Docker image
- [ ] Deploy to Azure App Service
- [ ] Configure database connection (managed identity or password)
- [ ] Set up RBAC for storage account access
- [ ] Verify STAC search endpoints
- [ ] Verify mosaic tile generation
- [ ] Test with real STAC catalog data

**Success Criteria**:
- ✅ STAC search queries return results
- ✅ Mosaic tiles generated from search
- ✅ Assets from multiple containers accessed seamlessly
- ✅ OAuth token grants access to all referenced containers
- ✅ Performance acceptable for real-world usage

---

## Phase 3: Multi-Container Testing & Validation

**Objective**: Thoroughly test OAuth approach with multiple Azure blob containers

**Priority**: MEDIUM
**Timeline**: 1-2 days
**Status**: 🔴 Blocked by Phase 1
**Depends On**: Phase 1 completion

### Tasks

#### 3.1 Test Environment Setup
- [ ] Create additional blob containers (bronze-cogs, gold-cogs)
- [ ] Upload sample COGs to each container
- [ ] Grant Managed Identity read access to all containers
- [ ] Create STAC items referencing assets in different containers

#### 3.2 Access Testing
- [ ] Test OAuth token with container: silver-cogs
- [ ] Test OAuth token with container: bronze-cogs
- [ ] Test OAuth token with container: gold-cogs
- [ ] Verify same token works for all containers
- [ ] Test simultaneous access to multiple containers in one request

#### 3.3 RBAC Validation
- [ ] Test with Storage Blob Data Reader role (current)
- [ ] Test with container-specific role assignments
- [ ] Verify denial when role not assigned to container
- [ ] Document least-privilege RBAC patterns

#### 3.4 Performance Analysis
- [ ] Measure token acquisition time (OAuth vs SAS)
- [ ] Test token caching effectiveness
- [ ] Measure tile generation time across containers
- [ ] Compare performance: single container vs multi-container

---

## Phase 4: Production Hardening & Monitoring

**Objective**: Ensure production readiness with monitoring, alerts, and best practices

**Priority**: LOW
**Timeline**: 2-3 days
**Status**: 🔴 Blocked by Phase 2

### Tasks

#### 4.1 Monitoring Setup
- [ ] Enable Application Insights integration
- [ ] Create custom metrics for OAuth token generation
- [ ] Track token refresh frequency
- [ ] Monitor GDAL /vsiaz/ access patterns
- [ ] Set up alerts for authentication failures

#### 4.2 Security Hardening
- [ ] Review token caching security (memory-only)
- [ ] Ensure tokens not logged
- [ ] Implement token rotation best practices
- [ ] Review RBAC assignments (least privilege)
- [ ] Enable Azure Storage analytics logging

#### 4.3 Operational Documentation
- [ ] Create runbook for common issues
- [ ] Document OAuth token troubleshooting
- [ ] Create disaster recovery procedures
- [ ] Document scaling strategies
- [ ] Create monitoring dashboard

---

## Future Enhancements

**Priority**: LOW
**Timeline**: TBD

### Potential Improvements
- [ ] Support for multiple storage accounts (not just multiple containers)
- [ ] User-assigned managed identity support
- [ ] Custom GDAL environment variable management
- [ ] Advanced caching strategies (Redis?)
- [ ] Metrics and observability improvements
- [ ] Cost optimization analysis
- [ ] Regional replication strategies

---

## Version History

### v2.0.0-oauth (Planned)
- **OAuth Token Authentication**: Simplify authentication with direct OAuth tokens
- **Multi-Container Support**: Single token works for all containers
- **Code Reduction**: Remove ~150 lines of SAS generation code
- **Dependency Reduction**: Remove `azure-storage-blob` dependency
- **Improved Logging**: Better visibility into OAuth token lifecycle

### v1.0.2 (Current - Production)
- **Fix**: User Delegation SAS with container-specific scope
- **Fix**: Container name changed from wildcard to silver-cogs
- **Working**: All endpoints verified in production

### v1.0.1
- **Fix**: Module import path corrected (custom_main:app)

### v1.0.0
- **Initial**: User Delegation SAS with wildcard container (didn't work)

---

## Key Decisions

### Decision 1: OAuth Tokens vs SAS Tokens
**Date**: November 7, 2025
**Decision**: Migrate from User Delegation SAS to OAuth tokens
**Rationale**:
- SAS tokens are for *restricting* access (delegation to untrusted clients)
- OAuth tokens are for *granting* identity-based access (service-to-service)
- OAuth solves multi-container problem automatically
- Simpler code, fewer dependencies, better alignment with RBAC model

### Decision 2: TiTiler-pgSTAC as Separate Project
**Date**: November 7, 2025
**Decision**: Create new project for TiTiler-pgSTAC instead of extending current
**Rationale**:
- Different base Docker image
- Additional dependencies (PostgreSQL)
- Different use case (STAC catalog vs direct COG URLs)
- Cleaner separation of concerns
- Can reuse authentication code via copy/import

---

## Success Metrics

### Phase 1 Success
- [ ] Code complexity reduced by >50%
- [ ] Dependencies reduced (remove azure-storage-blob)
- [ ] Single token works for multiple containers
- [ ] Production deployment successful
- [ ] All existing functionality preserved

### Phase 2 Success
- [ ] TiTiler-pgSTAC deployed and operational
- [ ] STAC search → tile generation working
- [ ] Multi-container assets accessed seamlessly
- [ ] Performance acceptable (<2s for mosaic tile)
- [ ] Documentation complete

### Overall Success
- [ ] OAuth approach proven in production
- [ ] Multi-container access working
- [ ] Both TiTiler and TiTiler-pgSTAC deployed
- [ ] Comprehensive documentation
- [ ] Monitoring and alerts operational

---

## Notes

### Why OAuth is Better
- **Simplicity**: ~50 lines vs ~200 lines
- **Scope**: Account-wide vs container-specific
- **Multi-container**: Automatic vs manual token management
- **Alignment**: Direct RBAC vs additional restriction layer
- **Use Case**: Service auth vs client delegation

### Risks & Mitigations
| Risk | Impact | Mitigation |
|------|--------|-----------|
| OAuth token doesn't work with GDAL | HIGH | Test locally before production deployment |
| Performance regression | MEDIUM | Benchmark before/after migration |
| Breaking change for clients | LOW | No client-facing changes expected |
| Token refresh issues | MEDIUM | Comprehensive testing of refresh logic |

---

**Next Action**: Begin Phase 1, Task 1.1 - Read current implementation and create OAuth version

