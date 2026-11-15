# REST API

The API is served under `/api`; use `Authorization: Bearer <access_token>` for
protected routes. FastAPI publishes an interactive OpenAPI document at
`/docs`.

## Authentication

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/register` | Register researcher. Optional `bootstrap_token` grants the configured initial admin role when both email and token match server environment. |
| POST | `/api/auth/login` | Verify credentials and return an access token. |
| GET | `/api/auth/me` | Return the authenticated user's ID, email, and role. |

Passwords must be at least ten characters. Password hashes use PBKDF2-HMAC
SHA-256 with random salts. Access tokens are HMAC-signed and expire according
to `JWT_LIFETIME_SECONDS`.

## Experiments and artifacts

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/experiments/train` | Queue controlled training. Returns `experiment_id` and status. |
| GET | `/api/experiments` | List owned and public experiments (admin sees all). |
| GET | `/api/experiments/{id}` | View experiment configuration, metrics, artifacts, and transactions. |
| GET | `/api/artifacts/{artifact_id}/download` | Download an authorized local artifact. |
| GET | `/api/experiments/{id}/report` | Download a JSON experiment/evidence/reproduction report. |

Training body example:

```json
{
  "name": "Baseline logistic regression",
  "description": "Bundled classification dataset, fixed holdout split",
  "model_name": "logistic_regression",
  "hyperparameters": { "C": 1.0, "max_iter": 1000 },
  "random_seed": 42,
  "version": 1,
  "visibility": "private",
  "source_repository": "https://example.invalid/research/project",
  "git_commit": "0123456789abcdef0123456789abcdef01234567",
  "preprocessing": ["stratified_train_test_split"]
}
```

Only the three built-in estimator types and their allowlisted parameters are
accepted. The dataset is the bundled Breast Cancer Wisconsin classification
dataset. Arbitrary dataset or source-code uploads are not accepted or executed.
Duplicate owner/name/version combinations return HTTP 409.

Experiment state transitions are `queued → running → completed|failed`. The
current implementation stores state in the database, but uses an in-process
FastAPI background task; jobs are not recovered after an API-process crash.

## Blockchain and evidence

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/blockchain/status` | Report actual RPC connectivity and deployed contract-code status; never returns private key data. |
| POST | `/api/experiments/{id}/register-on-chain` | Sign a transaction on the configured EVM network, await a mined receipt, then check contract read-back. |
| GET | `/api/experiments/{id}/transactions` | List actual transaction status and receipt metadata. |
| POST | `/api/experiments/{id}/verify` | Re-hash every artifact and query both contract verification and stored record. |

A registration request returns a transaction hash only if a transaction was
actually submitted. It reports `confirmed` only after a successful receipt and
matching read-back. Transactions that were broadcast but could not be
confirmed are recorded as `pending`; a reverted receipt is `failed`. The
backend must be configured with an RPC URL, chain ID, deployed contract
address, and dedicated service wallet. For local development, use a disposable
Hardhat account. No simulated blockchain mode exists.

Canonicalization is UTF-8 JSON, sorted object keys, compact separators,
Unicode emitted directly, and array order preserved. The manifest includes
`reproducibilitychain-json-v1`; its SHA-256 digest is stored as
`sha256:<lowercase hex>`. See `docs/architecture.md`.

## Reproductions, comparisons, and scores

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/experiments/{id}/reproductions` | Queue a controlled rerun. Optional body configures metric tolerances and can override model/hyperparameters/seed for changed-config comparisons. |
| GET | `/api/reproductions/{id}` | Poll status, environment, metric-by-metric comparison, and score. |
| GET | `/api/scores/{reproduction_id}` | Retrieve the score breakdown and deduction reasons. |

Default tolerances are 0.02 absolute for accuracy, precision, recall, F1, and
ROC-AUC. The proposed weighted score is artifact integrity 40, configuration
match 20, metric agreement 30, and environment match 10. Critical integrity or
chain failure caps the score at 30. It is not a scientifically universal
measure.

## Dashboard and administration

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/dashboard` | Counts, recent transactions, experiment history, and score distribution. |
| GET | `/api/admin/users` | Admin-only user list. |
| GET | `/api/admin/audit-logs?limit=100` | Admin-only audit events; `limit` must be 1–500. |

Private experiment details and artifacts are hidden from other researchers.
Marking an experiment `public` permits authenticated researchers to view its
evidence and reproduce the controlled pipeline.

