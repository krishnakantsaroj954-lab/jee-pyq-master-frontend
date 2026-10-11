from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any

@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    blocking: bool = True
    question_id: str | None = None

@dataclass
class Question:
    id: str
    source_question_number: int
    text: str
    options: dict[str, str]
    answer: str | None
    pages: list[int]
    bounds: list[float]
    provenance: dict[str, Any]
    assets: list[dict[str, Any]] = field(default_factory=list)
    solution: dict[str, Any] | None = None
    requires_figure: bool = False
    status: str = "VALIDATED"
    issues: list[Issue] = field(default_factory=list)
    subject: str | None = None
    section: str | None = None
    question_type: str = "UNKNOWN"
    solution_assets: list[dict[str, Any]] = field(default_factory=list)

    def json(self) -> dict[str, Any]:
        value = asdict(self)
        value["issues"] = [asdict(i) for i in self.issues]
        return value
