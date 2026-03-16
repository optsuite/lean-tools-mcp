# Author: Ziyu Wang
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Type definitions for LSP requests and responses.

Covers standard LSP types and Lean-specific custom requests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


# ---------------------------------------------------------------------------
# LSP Position / Range
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Position:
    """LSP position (0-based line and character)."""

    line: int
    character: int

    def to_dict(self) -> dict[str, int]:
        return {"line": self.line, "character": self.character}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Position:
        return cls(line=d["line"], character=d["character"])


@dataclass(slots=True)
class Range:
    """LSP range with start and end positions."""

    start: Position
    end: Position

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start.to_dict(), "end": self.end.to_dict()}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Range:
        return cls(
            start=Position.from_dict(d["start"]),
            end=Position.from_dict(d["end"]),
        )


# ---------------------------------------------------------------------------
# LSP Diagnostic
# ---------------------------------------------------------------------------

class DiagnosticSeverity(IntEnum):
    ERROR = 1
    WARNING = 2
    INFORMATION = 3
    HINT = 4


@dataclass(slots=True)
class Diagnostic:
    """A single LSP diagnostic message."""

    range: Range
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    source: str = "lean4"
    code: str | None = None
    full_range: Range | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "range": self.range.to_dict(),
            "message": self.message,
            "severity": int(self.severity),
            "source": self.source,
        }
        if self.code is not None:
            d["code"] = self.code
        if self.full_range is not None:
            d["fullRange"] = self.full_range.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Diagnostic:
        return cls(
            range=Range.from_dict(d["range"]),
            message=d.get("message", ""),
            severity=DiagnosticSeverity(d.get("severity", 1)),
            source=d.get("source", "lean4"),
            code=d.get("code"),
            full_range=Range.from_dict(d["fullRange"]) if "fullRange" in d else None,
        )


# ---------------------------------------------------------------------------
# LSP TextDocumentIdentifier / Item
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TextDocumentIdentifier:
    uri: str

    def to_dict(self) -> dict[str, str]:
        return {"uri": self.uri}


@dataclass(slots=True)
class TextDocumentItem:
    uri: str
    language_id: str
    version: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "languageId": self.language_id,
            "version": self.version,
            "text": self.text,
        }


@dataclass(slots=True)
class VersionedTextDocumentIdentifier:
    uri: str
    version: int

    def to_dict(self) -> dict[str, Any]:
        return {"uri": self.uri, "version": self.version}


# ---------------------------------------------------------------------------
# Lean-specific types
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PlainGoal:
    """Response from $/lean/plainGoal."""

    rendered: str
    goals: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> PlainGoal | None:
        if d is None:
            return None
        return cls(
            rendered=d.get("rendered", ""),
            goals=d.get("goals", []),
        )


@dataclass(slots=True)
class PlainTermGoal:
    """Response from $/lean/plainTermGoal."""

    goal: str
    range: Range | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> PlainTermGoal | None:
        if d is None:
            return None
        return cls(
            goal=d.get("goal", ""),
            range=Range.from_dict(d["range"]) if "range" in d else None,
        )


# ---------------------------------------------------------------------------
# File progress (Lean custom notification)
# ---------------------------------------------------------------------------

class FileProgressKind(IntEnum):
    PROCESSING = 1
    FATAL_ERROR = 2


@dataclass(slots=True)
class FileProgressProcessingInfo:
    range: Range
    kind: FileProgressKind = FileProgressKind.PROCESSING

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FileProgressProcessingInfo:
        return cls(
            range=Range.from_dict(d["range"]),
            kind=FileProgressKind(d.get("kind", 1)),
        )


# ---------------------------------------------------------------------------
# $/lean/tryTactics response
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TacticResult:
    """Result for a single tactic attempt from $/lean/tryTactics."""

    tactic: str
    goals: list[str] | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TacticResult:
        return cls(
            tactic=d.get("tactic", ""),
            goals=d.get("goals"),
            error=d.get("error"),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"tactic": self.tactic}
        if self.goals is not None:
            d["goals"] = self.goals
        if self.error is not None:
            d["error"] = self.error
        return d
