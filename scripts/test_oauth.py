#!/usr/bin/env python3
"""Test OAuth token acquisition."""

import os
from azure.identity import DefaultAzureCredential

def test_oauth():
    """Test OAuth token acquisition for Azure Storage."""

    storage_account = os.getenv("AZURE_STORAGE_ACCOUNT", "rmhazuregeo")

    print("=" * 80)
    print("Testing OAuth Token Acquisition")
    print("=" * 80)
    print(f"Storage Account: {storage_account}")
    print(f"Token Scope: https://storage.azure.com/.default")
    print("=" * 80)

    try:
        # Create credential
        print("\nStep 1: Creating DefaultAzureCredential...")
        credential = DefaultAzureCredential()
        print("✓ Credential created successfully")

        # Get token
        print("\nStep 2: Requesting OAuth token...")
        token = credential.get_token("https://storage.azure.com/.default")

        print("✓ Token acquired successfully")
        print(f"  Token length: {len(token.token)} characters")
        print(f"  Token starts with: {token.token[:20]}...")
        print(f"  Token expires: {token.expires_on}")

        print("\n" + "=" * 80)
        print("✅ OAuth authentication test PASSED")
        print("=" * 80)

        return True

    except Exception as e:
        print(f"\n❌ OAuth authentication test FAILED")
        print(f"Error: {type(e).__name__}: {str(e)}")
        print("\nTroubleshooting:")
        print("  - Run: az login")
        print("  - Verify: az account show")
        print("  - Check RBAC: az role assignment list --assignee <principal-id>")
        return False

if __name__ == "__main__":
    success = test_oauth()
    exit(0 if success else 1)
