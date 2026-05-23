from sqlalchemy import Column, Integer, Text, DateTime, String, Index, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import declarative_base

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
    orchestrator_descriptor_id = Column(Integer, ForeignKey('orchestrator_descriptor.id'), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class ReleaseStepExecution(Base):
    __tablename__ = "release_step_execution"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    release_execution_id = Column(Integer, ForeignKey('release_execution.id'), nullable=False)
    stage_id = Column(String, nullable=False)
    step_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    message = Column(Text, nullable=True)
    job_execution_correlation_id = Column(Integer, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index('ix_release_step_execution_execution_stage_step', 'release_execution_id', 'stage_id', 'step_id', unique=True),
    )
