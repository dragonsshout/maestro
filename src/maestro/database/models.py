from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class OrchestratorDescriptor(Base):
    __tablename__ = "orchestrator_descriptor"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    name = Column(String, nullable=False, unique=True)
    yaml = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReleaseExecution(Base):
    __tablename__ = "release_execution"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    message = Column(Text, nullable=True)
    orchestrator_descriptor_id = Column(Integer, ForeignKey("orchestrator_descriptor.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ReleaseStepExecution(Base):
    __tablename__ = "release_step_execution"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    release_execution_id = Column(Integer, ForeignKey("release_execution.id"), nullable=False)
    stage_id = Column(String, nullable=False)
    step_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    message = Column(Text, nullable=True)
    job_execution_correlation_id = Column(Integer, nullable=True)
    job_input_id = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index(
            "ix_release_step_execution_execution_stage_step",
            "release_execution_id",
            "stage_id",
            "step_id",
            unique=True,
        ),
    )


class UISettings(Base):
    __tablename__ = "ui_settings"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    key = Column(String, nullable=False, unique=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class StepEvent(Base):
    __tablename__ = "step_event"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    job_execution_correlation_id = Column(Integer, nullable=False, index=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ScheduledRelease(Base):
    __tablename__ = "scheduled_release"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    orchestrator_descriptor_id = Column(Integer, ForeignKey("orchestrator_descriptor.id"), nullable=False)
    name = Column(String, nullable=False)
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, nullable=False, default="pending")
    release_execution_id = Column(Integer, ForeignKey("release_execution.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (Index("ix_scheduled_release_name_status", "name", "status"),)


class ExecutionActionLog(Base):
    """Histórico de ações manuais tomadas sobre uma execução de release."""

    __tablename__ = "execution_action_log"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    release_execution_id = Column(Integer, ForeignKey("release_execution.id"), nullable=False, index=True)
    # approve | deny | retry_step | resolve_timeout_success | resolve_timeout_failure
    action = Column(String, nullable=False)
    step_execution_id = Column(Integer, ForeignKey("release_step_execution.id"), nullable=True)
    stage_id = Column(String, nullable=True)
    step_id = Column(String, nullable=True)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class JobPathRegistry(Base):
    """Cadastro de job paths por repositório e environment."""

    __tablename__ = "job_path_registry"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    repository = Column(String, nullable=False)
    environment = Column(String, nullable=False)
    domain = Column(String, nullable=True)
    type = Column(String, nullable=False, default="jenkins")
    path = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("repository", "environment", name="uq_job_path_registry_repository_environment"),
    )
