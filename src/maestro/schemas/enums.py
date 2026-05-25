from enum import Enum

class ExecutionStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"
    ABORTED = "aborted"
    WAITING_APPROVAL = "waiting_approval"
