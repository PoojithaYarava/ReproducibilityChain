from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="researcher")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    experiments: Mapped[list["Experiment"]] = relationship(back_populates="owner")


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", "version", name="uq_owner_experiment_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    visibility: Mapped[str] = mapped_column(String(16), default="private")
    status: Mapped[str] = mapped_column(String(24), default="queued")
    dataset_name: Mapped[str] = mapped_column(String(80), default="breast_cancer")
    dataset_version: Mapped[str] = mapped_column(String(80), default="sklearn-bundled")
    source_repository: Mapped[str | None] = mapped_column(String(500), nullable=True)
    git_commit: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manifest_hash: Mapped[str | None] = mapped_column(String(71), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[User] = relationship(back_populates="experiments")
    configuration: Mapped["ExperimentConfiguration | None"] = relationship(
        back_populates="experiment", uselist=False, cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["ExperimentArtifact"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )
    metrics: Mapped["ExperimentMetrics | None"] = relationship(
        back_populates="experiment", uselist=False, cascade="all, delete-orphan"
    )
    transactions: Mapped[list["BlockchainTransaction"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )


class ExperimentConfiguration(Base):
    __tablename__ = "experiment_configurations"

    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id"), primary_key=True
    )
    model_name: Mapped[str] = mapped_column(String(40))
    hyperparameters: Mapped[dict] = mapped_column(JSON)
    random_seed: Mapped[int] = mapped_column(Integer)
    preprocessing: Mapped[list[str]] = mapped_column(JSON)
    environment: Mapped[dict] = mapped_column(JSON, default=dict)
    experiment: Mapped[Experiment] = relationship(back_populates="configuration")


class ExperimentArtifact(Base):
    __tablename__ = "experiment_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(40))
    file_name: Mapped[str] = mapped_column(String(160))
    relative_path: Mapped[str] = mapped_column(String(500), unique=True)
    sha256: Mapped[str] = mapped_column(String(71))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    experiment: Mapped[Experiment] = relationship(back_populates="artifacts")


class ExperimentMetrics(Base):
    __tablename__ = "experiment_metrics"

    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id"), primary_key=True
    )
    values: Mapped[dict] = mapped_column(JSON)
    confusion_matrix: Mapped[list[list[int]]] = mapped_column(JSON)
    execution_seconds: Mapped[float] = mapped_column(Float)
    experiment: Mapped[Experiment] = relationship(back_populates="metrics")


class BlockchainTransaction(Base):
    __tablename__ = "blockchain_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    manifest_hash: Mapped[str] = mapped_column(String(71))
    transaction_hash: Mapped[str] = mapped_column(String(66), unique=True)
    status: Mapped[str] = mapped_column(String(16))
    block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signer_address: Mapped[str | None] = mapped_column(String(42), nullable=True)
    chain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    experiment: Mapped[Experiment] = relationship(back_populates="transactions")


class ReproductionAttempt(Base):
    __tablename__ = "reproduction_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    environment: Mapped[dict] = mapped_column(JSON, default=dict)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    tolerances: Mapped[dict] = mapped_column(JSON, default=dict)
    configuration_hash: Mapped[str | None] = mapped_column(String(71), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class VerificationResult(Base):
    __tablename__ = "verification_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    artifacts_match: Mapped[bool] = mapped_column(Boolean)
    chain_match: Mapped[bool] = mapped_column(Boolean)
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReproducibilityScore(Base):
    __tablename__ = "reproducibility_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    reproduction_id: Mapped[str] = mapped_column(ForeignKey("reproduction_attempts.id"))
    total: Mapped[float] = mapped_column(Float)
    components: Mapped[dict] = mapped_column(JSON)
    reasons: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
