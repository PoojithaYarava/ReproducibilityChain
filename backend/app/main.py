import json
import hmac
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app import models
from app.blockchain import (
    BlockchainError,
    anchor_manifest,
    network_status,
    verify_manifest,
)
from app.config import (
    BOOTSTRAP_ADMIN_EMAIL,
    BOOTSTRAP_ADMIN_TOKEN,
    CORS_ORIGINS,
    MAX_ARTIFACT_BYTES,
    STORAGE_ROOT,
)
from app.db import Base, SessionLocal, engine, get_db
from app.evidence import canonical_json_bytes, sha256_bytes, sha256_file
from app.ml_engine import ALLOWED_MODELS, _make_model, run_pipeline
from app.models import (
    AuditLog,
    BlockchainTransaction,
    Experiment,
    ExperimentArtifact,
    ExperimentConfiguration,
    ExperimentMetrics,
    ReproducibilityScore,
    ReproductionAttempt,
    User,
    VerificationResult,
)
from app.schemas import Credentials, ReproductionRequest, TrainingRequest
from app.scoring import calculate_score
from app.security import create_access_token, current_user, hash_password, require_admin, verify_password

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reproducibility_chain")

app = FastAPI(
    title="ReproducibilityChain API",
    description=(
        "Local prototype API for experiment training, cryptographic evidence, "
        "confirmed blockchain anchoring, and reproduction."
    ),
    version="0.2.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.on_event("startup")
def initialize_local_storage() -> None:
    Base.metadata.create_all(bind=engine)
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)


def _audit(
    db: Session,
    user_id: str | None,
    action: str,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource_id=resource_id,
            details=details or {},
        )
    )


def _experiment_access(db: Session, experiment_id: str, user: User) -> Experiment:
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if (
        user.role != "admin"
        and user.id != experiment.owner_id
        and experiment.visibility != "public"
    ):
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiment


def _jsonable_time(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _artifact_json(artifact: ExperimentArtifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "type": artifact.artifact_type,
        "file_name": artifact.file_name,
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
        "download_url": f"/api/artifacts/{artifact.id}/download",
    }


def _experiment_json(experiment: Experiment, include_private: bool = True) -> dict[str, Any]:
    return {
        "id": experiment.id,
        "owner_id": experiment.owner_id if include_private else None,
        "owner_email": experiment.owner.email if include_private and experiment.owner else None,
        "name": experiment.name,
        "description": experiment.description,
        "version": experiment.version,
        "visibility": experiment.visibility,
        "status": experiment.status,
        "dataset_name": experiment.dataset_name,
        "dataset_version": experiment.dataset_version,
        "source_repository": experiment.source_repository,
        "git_commit": experiment.git_commit,
        "manifest_hash": experiment.manifest_hash,
        "error_message": experiment.error_message,
        "created_at": _jsonable_time(experiment.created_at),
        "configuration": (
            {
                "model_name": experiment.configuration.model_name,
                "hyperparameters": experiment.configuration.hyperparameters,
                "random_seed": experiment.configuration.random_seed,
                "preprocessing": experiment.configuration.preprocessing,
                "environment": experiment.configuration.environment,
            }
            if experiment.configuration
            else None
        ),
        "metrics": (
            {
                "values": experiment.metrics.values,
                "confusion_matrix": experiment.metrics.confusion_matrix,
                "execution_seconds": experiment.metrics.execution_seconds,
            }
            if experiment.metrics
            else None
        ),
        "artifacts": [_artifact_json(item) for item in experiment.artifacts],
        "transactions": [
            {
                "transaction_hash": tx.transaction_hash,
                "status": tx.status,
                "block_number": tx.block_number,
                "manifest_hash": tx.manifest_hash,
                "signer_address": tx.signer_address,
                "chain_id": tx.chain_id,
                "created_at": _jsonable_time(tx.created_at),
            }
            for tx in experiment.transactions
        ],
    }


def _artifact_directory(owner_id: str, experiment_id: str) -> Path:
    path = (STORAGE_ROOT / owner_id / experiment_id).resolve()
    if not path.is_relative_to(STORAGE_ROOT):
        raise RuntimeError("Resolved artifact path is outside storage root")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _record_pipeline_artifacts(
    db: Session, experiment: Experiment, directory: Path
) -> None:
    types = {
        "dataset.csv": "dataset",
        "model.joblib": "model",
        "configuration.json": "configuration",
        "environment.json": "environment",
        "metrics.json": "metrics",
        "source_reference.json": "source_reference",
        "source_code_snapshot.py": "source_code_snapshot",
    }
    for file_name, artifact_type in types.items():
        path = directory / file_name
        size = path.stat().st_size
        if size > MAX_ARTIFACT_BYTES:
            raise RuntimeError(f"Generated artifact exceeds configured size limit: {file_name}")
        db.add(
            ExperimentArtifact(
                experiment_id=experiment.id,
                artifact_type=artifact_type,
                file_name=file_name,
                relative_path=path.relative_to(STORAGE_ROOT).as_posix(),
                sha256=sha256_file(path),
                size_bytes=size,
            )
        )


def _build_manifest(db: Session, experiment: Experiment) -> dict[str, Any]:
    artifacts = db.scalars(
        select(ExperimentArtifact)
        .where(ExperimentArtifact.experiment_id == experiment.id)
        .order_by(ExperimentArtifact.artifact_type)
    ).all()
    return {
        "canonicalization": "reproducibilitychain-json-v1",
        "experiment": {
            "id": experiment.id,
            "name": experiment.name,
            "version": experiment.version,
            "description": experiment.description,
            "dataset_name": experiment.dataset_name,
            "dataset_version": experiment.dataset_version,
            "source_repository": experiment.source_repository,
            "git_commit": experiment.git_commit,
            "created_at": experiment.created_at.isoformat(),
        },
        "configuration": {
            "model_name": experiment.configuration.model_name,
            "hyperparameters": experiment.configuration.hyperparameters,
            "random_seed": experiment.configuration.random_seed,
            "preprocessing": experiment.configuration.preprocessing,
        },
        "metrics": {
            "values": experiment.metrics.values,
            "confusion_matrix": experiment.metrics.confusion_matrix,
            "execution_seconds": experiment.metrics.execution_seconds,
        },
        "environment": experiment.configuration.environment,
        "artifacts": [
            {
                "type": artifact.artifact_type,
                "file_name": artifact.file_name,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
            }
            for artifact in artifacts
        ],
    }


def _create_manifest(db: Session, experiment: Experiment, directory: Path) -> None:
    manifest = _build_manifest(db, experiment)
    content = canonical_json_bytes(manifest)
    path = directory / "manifest.json"
    path.write_bytes(content)
    if len(content) > MAX_ARTIFACT_BYTES:
        path.unlink(missing_ok=True)
        raise RuntimeError("Manifest exceeds configured artifact size limit")
    manifest_hash = sha256_bytes(content)
    db.add(
        ExperimentArtifact(
            experiment_id=experiment.id,
            artifact_type="manifest",
            file_name="manifest.json",
            relative_path=path.relative_to(STORAGE_ROOT).as_posix(),
            sha256=manifest_hash,
            size_bytes=len(content),
        )
    )
    experiment.manifest_hash = manifest_hash


def _run_training(experiment_id: str) -> None:
    db = SessionLocal()
    try:
        experiment = db.scalar(
            select(Experiment)
            .options(joinedload(Experiment.configuration))
            .where(Experiment.id == experiment_id)
        )
        if experiment is None:
            logger.error("Queued training experiment disappeared: %s", experiment_id)
            return
        experiment.status = "running"
        db.commit()
        directory = _artifact_directory(experiment.owner_id, experiment.id)
        result = run_pipeline(
            model_name=experiment.configuration.model_name,
            parameters=experiment.configuration.hyperparameters,
            seed=experiment.configuration.random_seed,
            artifact_directory=directory,
            source_repository=experiment.source_repository,
            git_commit=experiment.git_commit,
        )
        experiment.configuration.hyperparameters = result["configuration"]["hyperparameters"]
        experiment.configuration.environment = result["environment"]
        experiment.metrics = ExperimentMetrics(
            values=result["metrics"],
            confusion_matrix=result["confusion_matrix"],
            execution_seconds=result["execution_seconds"],
        )
        _record_pipeline_artifacts(db, experiment, directory)
        db.flush()
        _create_manifest(db, experiment, directory)
        experiment.status = "completed"
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Training failed for experiment %s", experiment_id)
        failed = db.get(Experiment, experiment_id)
        if failed:
            failed.status = "failed"
            failed.error_message = str(exc)[:1000]
            db.commit()
    finally:
        db.close()


def _artifact_path(artifact: ExperimentArtifact) -> Path:
    path = (STORAGE_ROOT / artifact.relative_path).resolve()
    if not path.is_relative_to(STORAGE_ROOT):
        raise HTTPException(status_code=500, detail="Artifact storage path is invalid")
    return path


def _verify_experiment(db: Session, experiment: Experiment) -> dict[str, Any]:
    artifacts = db.scalars(
        select(ExperimentArtifact).where(
            ExperimentArtifact.experiment_id == experiment.id
        )
    ).all()
    checked: list[dict[str, Any]] = []
    required_types = {
        "dataset",
        "model",
        "configuration",
        "environment",
        "metrics",
        "source_reference",
        "source_code_snapshot",
        "manifest",
    }
    recorded_types = {artifact.artifact_type for artifact in artifacts}
    missing_types = sorted(required_types - recorded_types)
    artifact_match = (
        bool(artifacts)
        and experiment.manifest_hash is not None
        and not missing_types
    )
    for artifact in artifacts:
        path = _artifact_path(artifact)
        exists = path.is_file()
        actual_hash = sha256_file(path) if exists else None
        matches = exists and actual_hash == artifact.sha256
        artifact_match = artifact_match and matches
        checked.append(
            {
                "artifact_id": artifact.id,
                "file_name": artifact.file_name,
                "expected_sha256": artifact.sha256,
                "actual_sha256": actual_hash,
                "exists": exists,
                "matches": matches,
            }
        )

    chain_detail: dict[str, Any] = {"configured": False, "matches": False}
    chain_match = False
    if experiment.manifest_hash:
        try:
            chain_detail = verify_manifest(
                experiment.id, experiment.version, experiment.manifest_hash
            )
            chain_detail["configured"] = True
            chain_match = bool(chain_detail["exists"] and chain_detail["manifest_matches"])
        except BlockchainError as exc:
            chain_detail["error"] = str(exc)
    return {
        "artifacts_match": artifact_match,
        "chain_match": chain_match,
        "verified": artifact_match and chain_match,
        "artifact_checks": checked,
        "missing_artifact_types": missing_types,
        "blockchain": chain_detail,
    }


def _run_reproduction(reproduction_id: str, tolerances: dict[str, float]) -> None:
    db = SessionLocal()
    try:
        attempt = db.get(ReproductionAttempt, reproduction_id)
        experiment = (
            db.scalar(
                select(Experiment)
                .options(
                    joinedload(Experiment.configuration),
                    joinedload(Experiment.metrics),
                    joinedload(Experiment.artifacts),
                )
                .where(Experiment.id == attempt.experiment_id)
            )
            if attempt
            else None
        )
        if attempt is None or experiment is None or not experiment.configuration:
            logger.error("Reproduction setup missing for %s", reproduction_id)
            return
        attempt.status = "running"
        db.commit()
        directory = (
            STORAGE_ROOT / "reproductions" / attempt.id
        ).resolve()
        if not directory.is_relative_to(STORAGE_ROOT):
            raise RuntimeError("Reproduction path escaped artifact storage")
        requested = attempt.configuration
        result = run_pipeline(
            model_name=requested["model_name"],
            parameters=requested["hyperparameters"],
            seed=requested["random_seed"],
            artifact_directory=directory,
            source_repository=experiment.source_repository,
            git_commit=experiment.git_commit,
        )
        reproduced_configuration = result["configuration"]
        config_matches = (
            canonical_json_bytes(reproduced_configuration)
            == canonical_json_bytes(
                {
                    "model_name": experiment.configuration.model_name,
                    "hyperparameters": experiment.configuration.hyperparameters,
                    "random_seed": experiment.configuration.random_seed,
                    "dataset_name": experiment.dataset_name,
                    "dataset_version": experiment.dataset_version,
                    "test_size": 0.2,
                    "stratified": True,
                }
            )
        )
        attempt.configuration = reproduced_configuration
        attempt.configuration_hash = sha256_bytes(
            canonical_json_bytes(reproduced_configuration)
        )
        attempt.metrics = {
            **result["metrics"],
            "confusion_matrix": result["confusion_matrix"],
            "execution_seconds": result["execution_seconds"],
        }
        attempt.environment = result["environment"]
        verification = _verify_experiment(db, experiment)
        score = calculate_score(
            integrity_verified=verification["verified"],
            configuration_matches=config_matches,
            original_metrics=experiment.metrics.values,
            reproduced_metrics=result["metrics"],
            environment_original=experiment.configuration.environment,
            environment_reproduced=result["environment"],
            tolerances=tolerances,
        )
        attempt.status = "completed"
        db.add(
            ReproducibilityScore(
                experiment_id=experiment.id,
                reproduction_id=attempt.id,
                total=score["total"],
                components=score["components"],
                reasons=score["reasons"],
            )
        )
        _audit(
            db,
            attempt.user_id,
            "reproduction.completed",
            experiment.id,
            {"reproduction_id": attempt.id, "score": score["total"]},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Reproduction failed: %s", reproduction_id)
        attempt = db.get(ReproductionAttempt, reproduction_id)
        if attempt:
            attempt.status = "failed"
            attempt.metrics = {"error": str(exc)[:1000]}
            db.commit()
    finally:
        db.close()


@app.get("/api/health", tags=["operations"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "reproducibility-chain-api"}


@app.get("/api/blockchain/status", tags=["blockchain"])
def blockchain_health() -> dict[str, Any]:
    return network_status()


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED, tags=["authentication"])
def register(payload: Credentials, db: Session = Depends(get_db)) -> dict[str, Any]:
    email = str(payload.email).lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Email is already registered")
    has_admin = db.scalar(select(User.id).where(User.role == "admin").limit(1))
    role = (
        "admin"
        if BOOTSTRAP_ADMIN_EMAIL
        and email == BOOTSTRAP_ADMIN_EMAIL
        and BOOTSTRAP_ADMIN_TOKEN
        and payload.bootstrap_token
        and hmac.compare_digest(BOOTSTRAP_ADMIN_TOKEN, payload.bootstrap_token)
        and has_admin is None
        else "researcher"
    )
    user = User(email=email, password_hash=hash_password(payload.password), role=role)
    db.add(user)
    try:
        db.flush()
        _audit(db, user.id, "auth.register", user.id, {"role": role})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email is already registered") from exc
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "role": user.role},
    }


@app.post("/api/auth/login", tags=["authentication"])
def login(payload: Credentials, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    _audit(db, user.id, "auth.login")
    db.commit()
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "role": user.role},
    }


@app.get("/api/auth/me", tags=["authentication"])
def who_am_i(user: User = Depends(current_user)) -> dict[str, str]:
    return {"id": user.id, "email": user.email, "role": user.role}


@app.post("/api/experiments/train", status_code=status.HTTP_202_ACCEPTED, tags=["experiments"])
def train_experiment(
    payload: TrainingRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, str]:
    if payload.model_name not in ALLOWED_MODELS:
        raise HTTPException(
            status_code=422,
            detail=f"model_name must be one of {', '.join(ALLOWED_MODELS)}",
        )
    try:
        _make_model(payload.model_name, payload.hyperparameters, payload.random_seed)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.visibility == "public" and user.role not in {"researcher", "admin"}:
        raise HTTPException(status_code=403, detail="Public experiment creation is not allowed")
    experiment = Experiment(
        owner_id=user.id,
        name=payload.name.strip(),
        description=payload.description,
        version=payload.version,
        visibility=payload.visibility,
        status="queued",
        source_repository=payload.source_repository,
        git_commit=payload.git_commit,
        configuration=ExperimentConfiguration(
            model_name=payload.model_name,
            hyperparameters=payload.hyperparameters,
            random_seed=payload.random_seed,
            preprocessing=payload.preprocessing,
            environment={},
        ),
    )
    db.add(experiment)
    try:
        db.flush()
        _audit(db, user.id, "experiment.training_queued", experiment.id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An experiment with this name and version already exists for this account",
        ) from exc
    background_tasks.add_task(_run_training, experiment.id)
    return {"experiment_id": experiment.id, "status": "queued"}


@app.get("/api/experiments", tags=["experiments"])
def list_experiments(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[dict[str, Any]]:
    statement = (
        select(Experiment)
        .options(
            joinedload(Experiment.owner),
            joinedload(Experiment.configuration),
            joinedload(Experiment.metrics),
            joinedload(Experiment.artifacts),
            joinedload(Experiment.transactions),
        )
        .order_by(Experiment.created_at.desc())
    )
    if user.role != "admin":
        statement = statement.where(
            or_(Experiment.owner_id == user.id, Experiment.visibility == "public")
        )
    return [
        _experiment_json(item, include_private=item.owner_id == user.id or user.role == "admin")
        for item in db.scalars(statement).unique().all()
    ]


@app.get("/api/experiments/{experiment_id}", tags=["experiments"])
def experiment_detail(
    experiment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    experiment = _experiment_access(db, experiment_id, user)
    experiment = db.scalar(
        select(Experiment)
        .options(
            joinedload(Experiment.owner),
            joinedload(Experiment.configuration),
            joinedload(Experiment.metrics),
            joinedload(Experiment.artifacts),
            joinedload(Experiment.transactions),
        )
        .where(Experiment.id == experiment.id)
    )
    assert experiment is not None
    return _experiment_json(
        experiment, include_private=experiment.owner_id == user.id or user.role == "admin"
    )


@app.post("/api/experiments/{experiment_id}/register-on-chain", tags=["blockchain"])
def register_on_chain(
    experiment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    experiment = _experiment_access(db, experiment_id, user)
    if experiment.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the owner or an administrator can register")
    if experiment.status != "completed" or not experiment.manifest_hash:
        raise HTTPException(status_code=409, detail="Experiment training and manifest must complete first")
    if db.scalar(
        select(BlockchainTransaction.id).where(
            BlockchainTransaction.experiment_id == experiment.id,
            BlockchainTransaction.status.in_(("confirmed", "pending", "unverified")),
        )
    ):
        raise HTTPException(
            status_code=409,
            detail="This experiment version already has a confirmed, pending, or unverified registration",
        )
    try:
        result = anchor_manifest(experiment.id, experiment.version, experiment.manifest_hash)
    except BlockchainError as exc:
        if exc.tx_hash:
            db.add(
                BlockchainTransaction(
                    experiment_id=experiment.id,
                    manifest_hash=experiment.manifest_hash,
                    transaction_hash=exc.tx_hash,
                    status=exc.tx_status,
                    block_number=exc.block_number,
                    signer_address=exc.signer_address,
                    chain_id=exc.chain_id,
                )
            )
        _audit(
            db,
            user.id,
            "blockchain.registration_failed",
            experiment.id,
            {"tx_hash": exc.tx_hash, "status": exc.tx_status, "reason": str(exc)},
        )
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    transaction = BlockchainTransaction(
        experiment_id=experiment.id,
        manifest_hash=experiment.manifest_hash,
        transaction_hash=result["transaction_hash"],
        status=result["status"],
        block_number=result["block_number"],
        signer_address=result["signer_address"],
        chain_id=result["chain_id"],
    )
    db.add(transaction)
    _audit(
        db,
        user.id,
        "blockchain.registration_confirmed",
        experiment.id,
        {
            "tx_hash": result["transaction_hash"],
            "block_number": result["block_number"],
            "chain_id": result["chain_id"],
        },
    )
    db.commit()
    return result


@app.get("/api/experiments/{experiment_id}/transactions", tags=["blockchain"])
def experiment_transactions(
    experiment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    experiment = _experiment_access(db, experiment_id, user)
    return [
        {
            "transaction_hash": tx.transaction_hash,
            "status": tx.status,
            "block_number": tx.block_number,
            "manifest_hash": tx.manifest_hash,
            "chain_id": tx.chain_id,
            "signer_address": tx.signer_address,
            "created_at": _jsonable_time(tx.created_at),
        }
        for tx in db.scalars(
            select(BlockchainTransaction)
            .where(BlockchainTransaction.experiment_id == experiment.id)
            .order_by(BlockchainTransaction.created_at.desc())
        )
    ]


@app.post("/api/experiments/{experiment_id}/verify", tags=["verification"])
def verify_experiment(
    experiment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    experiment = _experiment_access(db, experiment_id, user)
    result = _verify_experiment(db, experiment)
    db.add(
        VerificationResult(
            experiment_id=experiment.id,
            artifacts_match=result["artifacts_match"],
            chain_match=result["chain_match"],
            details=result,
        )
    )
    _audit(db, user.id, "experiment.verified", experiment.id, {"verified": result["verified"]})
    db.commit()
    return result


@app.get("/api/artifacts/{artifact_id}/download", tags=["artifacts"])
def download_artifact(
    artifact_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> FileResponse:
    artifact = db.get(ExperimentArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    experiment = _experiment_access(db, artifact.experiment_id, user)
    path = _artifact_path(artifact)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file is missing")
    return FileResponse(path, filename=artifact.file_name, media_type="application/octet-stream")


@app.post("/api/experiments/{experiment_id}/reproductions", status_code=202, tags=["reproductions"])
def start_reproduction(
    experiment_id: str,
    payload: ReproductionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, str]:
    experiment = _experiment_access(db, experiment_id, user)
    if experiment.status != "completed" or experiment.configuration is None:
        raise HTTPException(status_code=409, detail="Only completed experiments can be reproduced")
    attempt_id = str(uuid4())
    configuration = {
        "model_name": payload.model_name or experiment.configuration.model_name,
        "hyperparameters": (
            payload.hyperparameters
            if payload.hyperparameters is not None
            else experiment.configuration.hyperparameters
        ),
        "random_seed": (
            payload.random_seed
            if payload.random_seed is not None
            else experiment.configuration.random_seed
        ),
    }
    if configuration["model_name"] not in ALLOWED_MODELS:
        raise HTTPException(
            status_code=422,
            detail=f"model_name must be one of {', '.join(ALLOWED_MODELS)}",
        )
    try:
        _make_model(
            configuration["model_name"],
            configuration["hyperparameters"],
            configuration["random_seed"],
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    attempt = ReproductionAttempt(
        id=attempt_id,
        experiment_id=experiment.id,
        user_id=user.id,
        status="queued",
        metrics={},
        environment={},
        configuration=configuration,
        tolerances=payload.tolerances,
        configuration_hash=sha256_bytes(canonical_json_bytes(configuration)),
    )
    db.add(attempt)
    _audit(db, user.id, "reproduction.queued", experiment.id, {"reproduction_id": attempt_id})
    db.commit()
    background_tasks.add_task(_run_reproduction, attempt_id, payload.tolerances)
    return {"reproduction_id": attempt_id, "status": "queued"}


@app.get("/api/reproductions/{reproduction_id}", tags=["reproductions"])
def reproduction_detail(
    reproduction_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    attempt = db.get(ReproductionAttempt, reproduction_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="Reproduction attempt not found")
    experiment = _experiment_access(db, attempt.experiment_id, user)
    if user.role != "admin" and user.id != attempt.user_id and experiment.visibility != "public":
        raise HTTPException(status_code=404, detail="Reproduction attempt not found")
    score = db.scalar(
        select(ReproducibilityScore)
        .where(ReproducibilityScore.reproduction_id == attempt.id)
        .order_by(ReproducibilityScore.created_at.desc())
    )
    original_metrics = experiment.metrics.values if experiment.metrics else {}
    metric_comparison = [
        {
            "metric": key,
            "original": original_metrics[key],
            "reproduced": attempt.metrics[key],
            "absolute_difference": abs(
                float(original_metrics[key]) - float(attempt.metrics[key])
            ),
            "tolerance": attempt.tolerances.get(key, 0.02),
            "within_tolerance": abs(
                float(original_metrics[key]) - float(attempt.metrics[key])
            )
            <= attempt.tolerances.get(key, 0.02),
        }
        for key in ("accuracy", "precision", "recall", "f1", "roc_auc")
        if key in original_metrics and key in attempt.metrics
    ]
    return {
        "id": attempt.id,
        "experiment_id": attempt.experiment_id,
        "status": attempt.status,
        "metrics": attempt.metrics,
        "environment": attempt.environment,
        "configuration": attempt.configuration,
        "configuration_hash": attempt.configuration_hash,
        "metric_comparison": metric_comparison,
        "created_at": _jsonable_time(attempt.created_at),
        "score": (
            {
                "total": score.total,
                "components": score.components,
                "reasons": score.reasons,
                "note": "Proposed project metric; not a scientifically established universal score.",
            }
            if score
            else None
        ),
    }


@app.get("/api/scores/{reproduction_id}", tags=["scores"])
def reproduction_score(
    reproduction_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    attempt = db.get(ReproductionAttempt, reproduction_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="Reproduction attempt not found")
    experiment = _experiment_access(db, attempt.experiment_id, user)
    if user.role != "admin" and user.id != attempt.user_id and experiment.visibility != "public":
        raise HTTPException(status_code=404, detail="Reproduction attempt not found")
    score = db.scalar(
        select(ReproducibilityScore)
        .where(ReproducibilityScore.reproduction_id == attempt.id)
        .order_by(ReproducibilityScore.created_at.desc())
    )
    if score is None:
        raise HTTPException(status_code=409, detail="Reproduction score is not available yet")
    return {
        "total": score.total,
        "components": score.components,
        "reasons": score.reasons,
        "metric": "Proposed project metric; not a scientifically established universal measure.",
    }


@app.get("/api/experiments/{experiment_id}/report", tags=["reports"])
def download_experiment_report(
    experiment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    experiment = _experiment_access(db, experiment_id, user)
    experiment = db.scalar(
        select(Experiment)
        .options(
            joinedload(Experiment.owner),
            joinedload(Experiment.configuration),
            joinedload(Experiment.metrics),
            joinedload(Experiment.artifacts),
            joinedload(Experiment.transactions),
        )
        .where(Experiment.id == experiment.id)
    )
    assert experiment is not None
    data: dict[str, Any] = _experiment_json(experiment)
    verifications = db.scalars(
        select(VerificationResult)
        .where(VerificationResult.experiment_id == experiment.id)
        .order_by(VerificationResult.created_at.desc())
        .limit(10)
    ).all()
    reproductions = db.scalars(
        select(ReproductionAttempt).where(ReproductionAttempt.experiment_id == experiment.id)
    ).all()
    data["verification_history"] = [
        {
            "artifacts_match": item.artifacts_match,
            "chain_match": item.chain_match,
            "details": item.details,
            "created_at": _jsonable_time(item.created_at),
        }
        for item in verifications
    ]
    data["reproductions"] = [
        {
            "id": item.id,
            "status": item.status,
            "metrics": item.metrics,
            "created_at": _jsonable_time(item.created_at),
        }
        for item in reproductions
    ]
    scores = db.scalars(
        select(ReproducibilityScore)
        .where(ReproducibilityScore.experiment_id == experiment.id)
        .order_by(ReproducibilityScore.created_at.desc())
    ).all()
    data["scores"] = [
        {
            "reproduction_id": item.reproduction_id,
            "total": item.total,
            "components": item.components,
            "reasons": item.reasons,
            "created_at": _jsonable_time(item.created_at),
        }
        for item in scores
    ]
    data["report_generated_at"] = datetime.now(timezone.utc).isoformat()
    body = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="experiment-{experiment.id}-report.json"'
        },
    )


@app.get("/api/dashboard", tags=["dashboard"])
def dashboard(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict[str, Any]:
    scope = [] if user.role == "admin" else [
        or_(Experiment.owner_id == user.id, Experiment.visibility == "public")
    ]
    experiment_query = select(Experiment)
    if scope:
        experiment_query = experiment_query.where(*scope)
    experiments = db.scalars(experiment_query).all()
    experiment_ids = [item.id for item in experiments]
    verified_count = db.scalar(
        select(func.count(func.distinct(VerificationResult.experiment_id))).where(
            VerificationResult.experiment_id.in_(experiment_ids or [""]),
            VerificationResult.artifacts_match.is_(True),
            VerificationResult.chain_match.is_(True),
        )
    ) or 0
    reproduction_count = db.scalar(
        select(func.count(ReproductionAttempt.id)).where(
            ReproductionAttempt.experiment_id.in_(experiment_ids or [""])
        )
    ) or 0
    failed_verifications = db.scalar(
        select(func.count(VerificationResult.id)).where(
            VerificationResult.experiment_id.in_(experiment_ids or [""]),
            or_(
                VerificationResult.artifacts_match.is_(False),
                VerificationResult.chain_match.is_(False),
            ),
        )
    ) or 0
    recent_transactions = db.scalars(
        select(BlockchainTransaction)
        .where(BlockchainTransaction.experiment_id.in_(experiment_ids or [""]))
        .order_by(BlockchainTransaction.created_at.desc())
        .limit(8)
    ).all()
    scores = db.scalars(
        select(ReproducibilityScore)
        .where(ReproducibilityScore.experiment_id.in_(experiment_ids or [""]))
        .order_by(ReproducibilityScore.created_at.desc())
        .limit(20)
    ).all()
    return {
        "total_experiments": len(experiments),
        "verified_experiments": verified_count,
        "reproduction_attempts": reproduction_count,
        "failed_verification_attempts": failed_verifications,
        "recent_transactions": [
            {
                "experiment_id": item.experiment_id,
                "transaction_hash": item.transaction_hash,
                "status": item.status,
                "block_number": item.block_number,
                "chain_id": item.chain_id,
                "created_at": _jsonable_time(item.created_at),
            }
            for item in recent_transactions
        ],
        "score_distribution": [
            {"reproduction_id": item.reproduction_id, "score": item.total}
            for item in scores
        ],
        "recent_experiments": [
            _experiment_json(item, include_private=item.owner_id == user.id or user.role == "admin")
            for item in sorted(experiments, key=lambda exp: exp.created_at, reverse=True)[:10]
        ],
    }


@app.get("/api/admin/users", tags=["administration"])
def admin_users(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> list[dict[str, Any]]:
    return [
        {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "created_at": _jsonable_time(user.created_at),
        }
        for user in db.scalars(select(User).order_by(User.created_at.desc())).all()
    ]


@app.get("/api/admin/audit-logs", tags=["administration"])
def admin_audit_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[dict[str, Any]]:
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    return [
        {
            "id": log.id,
            "user_id": log.user_id,
            "action": log.action,
            "resource_id": log.resource_id,
            "details": log.details,
            "created_at": _jsonable_time(log.created_at),
        }
        for log in db.scalars(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        ).all()
    ]
