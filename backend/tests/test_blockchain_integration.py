import os
from uuid import uuid4

import pytest

from app.blockchain import anchor_manifest, verify_manifest
from app.evidence import sha256_bytes


pytestmark = pytest.mark.integration
CHAIN_CONFIGURED = all(
    os.getenv(key)
    for key in (
        "BLOCKCHAIN_RPC_URL",
        "BLOCKCHAIN_PRIVATE_KEY",
        "BLOCKCHAIN_CONTRACT_ADDRESS",
    )
)


@pytest.mark.skipif(
    not CHAIN_CONFIGURED,
    reason="Requires a running Hardhat node, deployed registry, and test wallet",
)
def test_real_local_registration_receipt_and_readback() -> None:
    experiment_id = f"integration-{uuid4()}"
    manifest_hash = sha256_bytes(b"integration manifest")
    result = anchor_manifest(experiment_id, 1, manifest_hash)

    assert result["status"] == "confirmed"
    assert result["transaction_hash"].startswith("0x")
    assert len(result["transaction_hash"]) == 66
    assert result["block_number"] > 0
    assert result["chain_id"] == int(os.getenv("BLOCKCHAIN_CHAIN_ID", "31337"))

    verified = verify_manifest(experiment_id, 1, manifest_hash)
    assert verified["exists"] is True
    assert verified["manifest_matches"] is True
