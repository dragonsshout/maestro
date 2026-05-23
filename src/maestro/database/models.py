from sqlalchemy import Column, Integer, Text, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class OrchestratorDescriptor(Base):
    __tablename__ = "orchestrator_descriptor"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    timestamp_inclusao = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    yaml = Column(Text, nullable=False)
