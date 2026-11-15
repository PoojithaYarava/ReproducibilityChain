from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    bootstrap_token: str | None = Field(default=None, max_length=256)


class TrainingRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    model_name: str
    hyperparameters: dict = Field(default_factory=dict)
    random_seed: int = Field(default=42, ge=0, le=2**32 - 1)
    version: int = Field(default=1, ge=1)
    visibility: str = "private"
    source_repository: str | None = Field(default=None, max_length=500)
    git_commit: str | None = Field(default=None, max_length=128)
    preprocessing: list[str] = Field(default_factory=lambda: ["stratified_train_test_split"])

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, value: str) -> str:
        if value not in {"private", "public"}:
            raise ValueError("visibility must be private or public")
        return value

    @field_validator("git_commit")
    @classmethod
    def validate_git_commit(cls, value: str | None) -> str | None:
        if value is not None and (
            not value or len(value) not in {7, 40, 64} or any(c not in "0123456789abcdefABCDEF" for c in value)
        ):
            raise ValueError("git_commit must be a 7, 40, or 64 character hexadecimal commit")
        return value

    @field_validator("preprocessing")
    @classmethod
    def validate_preprocessing(cls, value: list[str]) -> list[str]:
        supported = ["stratified_train_test_split"]
        if value != supported:
            raise ValueError(
                "Only the built-in stratified_train_test_split workflow is supported"
            )
        return value


class ReproductionRequest(BaseModel):
    model_name: str | None = None
    hyperparameters: dict | None = None
    random_seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    tolerances: dict[str, float] = Field(
        default_factory=lambda: {
            "accuracy": 0.02,
            "precision": 0.02,
            "recall": 0.02,
            "f1": 0.02,
            "roc_auc": 0.02,
        }
    )

    @field_validator("tolerances")
    @classmethod
    def validate_tolerances(cls, value: dict[str, float]) -> dict[str, float]:
        supported = {"accuracy", "precision", "recall", "f1", "roc_auc"}
        if set(value) - supported or any(tol < 0 or tol > 1 for tol in value.values()):
            raise ValueError("Tolerances must be 0–1 values for supported metrics")
        return value


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: EmailStr
    role: str
