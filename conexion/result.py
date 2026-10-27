from dataclasses import dataclass


@dataclass(frozen=True)
class RequestResult:
    status: str
    attempts: int = 0
    email: str = ""
    reason: str = ""
    request_id: str = ""
    submitted: bool = False
