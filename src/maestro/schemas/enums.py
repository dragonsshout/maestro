from enum import Enum

class ExecutionStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"
    ABORTED = "aborted"
    WAITING_APPROVAL = "waiting_approval"

    @classmethod
    def from_string(cls, value: str) -> "ExecutionStatus":
        """Retorna o enum correspondente a partir de uma string (case-insensitive)."""
        for member in cls:
            if member.value.lower() == value.lower():
                return member
        raise ValueError(f"'{value}' is not a valid {cls.__name__}")
