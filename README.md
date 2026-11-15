# ReproducibilityChain

A local research prototype for recording, anchoring, and checking evidence for
controlled machine-learning experiments. It trains a built-in scikit-learn
classifier, stores generated files off-chain, hashes a canonical manifest with
SHA-256, and can write that commitment to a local Hardhat EVM.

> **Prototype boundary:** the local blockchain transaction is real only when a
> Hardhat node is running, a contract is deployed, and the backend confirms a
> mined receipt and matching contract read-back. The app does not claim public
> blockchain attestation or scientific validity.

## What works in this implementation

- Researcher registration/login with salted PBKDF2 password hashes and
  bearer-token protected endpoints. A bootstrap token is required to create
  the initial administrator.
- SQLite persistence through SQLAlchemy, with an Alembic baseline migration
  and an optional PostgreSQL driver.
- Controlled Logistic Regression, Random Forest, and Decision Tree training
  on scikit-learn's bundled Breast Cancer Wisconsin dataset.
- Generated dataset, model, configuration, environment, metrics, pipeline
  source snapshot, and source-reference artifacts stored locally.
- Canonical JSON manifest generation and SHA-256 evidence hashing.
- Solidity registry with version-aware duplicate prevention, events, reads,
  and on-chain verification.
- Backend-only signing against a configured chain, receipt checking, and
  contract read-back. No private key is sent to the browser.
- Artifact-integrity checks, controlled reruns, configurable metric tolerances,
  transparent score components, dashboard data, audit endpoints, and JSON
  reports.
- React UI for registration/login, dashboard, experiment execution and detail,
  chain registration, verification, reproductions, score reports, and admin
  views.

## Layout

```text
backend/       FastAPI, SQLAlchemy models, migrations, tests, ML pipeline
blockchain/    ExperimentRegistry Solidity contract, Hardhat scripts/tests
frontend/      React, TypeScript, Vite, Tailwind, Recharts UI
storage/       Generated local artifacts (ignored by Git)
docs/          Architecture, API, academic overview, validation notes
.env.example   Local configuration template (contains no keys)
```

## Windows setup (PowerShell)

Use three PowerShell terminals. Install Python 3.11+ and Node.js first.

### 1. Configure local secrets

From the repository root:

```powershell
Copy-Item .env.example .env
notepad .env
```

Replace `JWT_SECRET` with a randomly generated secret. For an administrator,
set `BOOTSTRAP_ADMIN_EMAIL` and a long random `BOOTSTRAP_ADMIN_TOKEN`; use that
email and token exactly once during registration. Never commit `.env` or paste
a real wallet key into source files.

### 2. Start the local blockchain

In terminal 1:

```powershell
Set-Location blockchain
npm ci
npm test
npm run node
```

Keep the Hardhat node open. It prints ephemeral development accounts and keys;
use only one of those local test accounts for the demo.

In terminal 2, deploy to the running node:

```powershell
Set-Location blockchain
npm run deploy:local
```

Copy the printed contract address into `BLOCKCHAIN_CONTRACT_ADDRESS` in the
root `.env`. Put the selected local Hardhat account's private key in
`BLOCKCHAIN_PRIVATE_KEY`. The key stays in the backend environment; it is
never placed in frontend configuration. The backend checks the configured
chain ID (31337 by default) and contract code before writing.

### 3. Start the backend

In terminal 3:

```powershell
Set-Location backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
alembic upgrade head
python -m uvicorn app.main:app --reload
```

Use `python -m pip install -e ".[dev,postgres]"` for PostgreSQL support. To
record runs in MLflow, install `python -m pip install -e ".[dev,mlflow]"` and
set `MLFLOW_TRACKING_URI`. If that variable is set without the optional package,
training fails explicitly.

The local administrator account is not pre-created. Register using the
configured bootstrap email and token, then register regular researchers.

### 4. Start the frontend

In terminal 4:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. FastAPI's OpenAPI page is at
`http://127.0.0.1:8000/docs`; API liveness is at
`http://127.0.0.1:8000/api/health`. The default CORS configuration also allows
Vite's fallback port 5174 when 5173 is already in use.

## End-to-end demonstration

1. Start the local Hardhat node, deploy `ExperimentRegistry`, and configure the
   contract address and a disposable Hardhat test key in `.env`.
2. Register a researcher and train an experiment using any of the three
   supported model types.
3. Wait for the persisted experiment status to become `completed`. Review the
   metrics and artifact hashes.
4. Choose **Anchor manifest on local chain**. The API returns success only
   after a mined transaction and matching registry read-back.
5. Choose **Verify artifacts + chain**. The result reports file checks and the
   on-chain comparison separately.
6. To demonstrate tamper detection, modify a copy of an artifact outside the
   application, then use a test-only script or API fixture to point verification
   at that copy. Do not alter valuable experiment data. Restore it after the
   test.
7. Choose **Run reproduction**. Compare metrics, review score components and
   deduction reasons, and download the JSON report.

The application does not provide an artifact-editing UI; tampering tests use
the storage path recorded in the database. Capture screenshots yourself from
the running local app; no screenshots or results are fabricated or committed.

## Validation commands

```powershell
# Backend tests
Set-Location backend
python -m pytest

# Smart contract compile and tests (Hardhat test uses its local in-process EVM)
Set-Location ..\blockchain
npm test

# Frontend type-check and production build
Set-Location ..\frontend
npm run build
```

Backend contract integration tests require a separately running local node,
the deployed contract address, and a disposable test-wallet key in environment
variables. Automated Solidity tests exercise actual local EVM transactions.

## Evidence and score interpretation

The canonical manifest format is UTF-8 JSON with lexicographically sorted
object keys, compact separators, Unicode emitted directly, and array order
preserved. The SHA-256 digest is stored as lowercase `sha256:<hex>`. The
manifest records its canonicalization version. Datasets, models, and reports
stay off-chain; only the experiment identifier, version, manifest hash,
researcher address, and timestamp are written to the registry.

The proposed score weights artifact integrity 40, configuration match 20,
metric agreement 30, and environment match 10. A failed or missing critical
integrity/chain check caps the total at 30. This score is a transparent project
heuristic, **not** a scientifically established universal reproducibility
metric. Hash agreement proves byte integrity against a commitment, not
methodological or scientific validity.

## Explicit limitations

- The training/reproduction worker uses FastAPI in-process background tasks.
  Job state is persisted, but the queue is not durable across process crashes;
  work is not Docker-isolated. Only maintained server-side pipeline code runs.
- The dataset and model choices are intentionally limited to the bundled
  dataset and three server-controlled scikit-learn estimators. There is no
  arbitrary dataset or Python upload endpoint.
- Files use local disk storage. There is no IPFS integration or cross-machine
  artifact replication.
- JSON reports are implemented; no PDF exporter, PowerPoint deck, or video
  script is included. These are omitted deliverables, not hidden functionality.
- The local Hardhat chain is ephemeral unless separately configured for
  persistence. Resetting it invalidates previous on-chain records.
- SQLite is the development default. PostgreSQL support is available through
  SQLAlchemy and the optional driver; production deployment hardening is not
  provided.
- `Base.metadata.create_all` supports local startup. Alembic migrations should
  be used and reviewed for managed deployments.

See [docs/architecture.md](docs/architecture.md),
[docs/api.md](docs/api.md), [docs/academic-overview.md](docs/academic-overview.md),
and [docs/testing.md](docs/testing.md).
