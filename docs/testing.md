# Validation and demonstration record

## Automated coverage

- Backend API tests cover registration/login, password hashing, authorization,
  duplicate version prevention, training, manifest/artifact hashes, tampering
  and missing-artifact detection, matching and changed-configuration
  reproductions, score components, preprocessing validation, and JSON report
  download.
- The Solidity Hardhat suite checks a real local EVM write/read-back, duplicate
  and versioned registrations, invalid inputs, and changed/missing commitments.
- An opt-in backend blockchain integration test exercises the Python signer,
  receipt, and read-back against a separately running local deployment.
- The frontend production build runs TypeScript validation and Vite bundling.

## Commands

From `backend/`:

```powershell
python -m pytest
python -m pytest -m integration
```

Integration test prerequisites: a local Hardhat node, deployed contract, and
environment variables `BLOCKCHAIN_RPC_URL`, `BLOCKCHAIN_CHAIN_ID`,
`BLOCKCHAIN_PRIVATE_KEY`, and `BLOCKCHAIN_CONTRACT_ADDRESS`. The default test
suite skips the integration case if these are absent.

From `blockchain/`:

```powershell
npm test
npm run compile
```

From `frontend/`:

```powershell
npm run build
```

## Results log

Only record measured results here after running the commands in the current
environment. Do not copy illustrative or expected values into this table.

| Check | Result | Environment / date |
|---|---|---|
| Backend pytest | Not run in this sandbox: Python package access was blocked by sandbox policy. | Fill after running |
| Hardhat compile/tests | Pending execution after dependency install. | Fill after running |
| Frontend build | Pass; TypeScript and Vite production build succeeded. | Local workspace |
| Backend-to-Hardhat integration | Not run; requires local node, deployment, and wallet configuration. | Fill after running |

## Manual screenshot plan

Capture screenshots directly from the running app; do not generate or imply
screenshots when the application was not run:

1. Registration/login and researcher dashboard.
2. Training form and completed experiment metrics.
3. Artifact manifest hashes and confirmed local transaction receipt.
4. Verification before and after modifying an expendable artifact copy.
5. Reproduction metric comparison and full score component breakdown.
6. Admin users and audit history (using the bootstrap admin account).

