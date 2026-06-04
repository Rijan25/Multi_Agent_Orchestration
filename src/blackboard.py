"""Shared blackboard. Append-only, versioned, immutable.

Agents never hand outputs to one another. An agent writes an artifact here,
and the orchestrator hands the next agent a reference (a string key) to read.
A retry writes v2; it never overwrites v1.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel


@dataclass
class ArtifactRecord:
    ref: str
    agent: str
    version: int
    payload: dict[str, Any]
    provenance: dict[str, Any]


class Blackboard:
    """In-memory store with a JSONL append on disk per run, for replay/audit."""

    def __init__(self, run_id: str, root: Path | str = "runs") -> None:
        self.run_id = run_id
        self._root = Path(root) / run_id
        self._root.mkdir(parents=True, exist_ok=True)
        self._log_path = self._root / "blackboard.jsonl"
        self._artifacts: dict[str, ArtifactRecord] = {}
        self._versions: dict[str, int] = {}
        self._lock = threading.Lock()

    def _next_version(self, agent: str) -> int:
        with self._lock:
            v = self._versions.get(agent, 0) + 1
            self._versions[agent] = v
            return v

    def write(
        self,
        agent: str,
        artifact: BaseModel,
        provenance: dict[str, Any] | None = None,
    ) -> str:
        """Write a new immutable, versioned artifact. Returns its ref."""
        version = self._next_version(agent)
        ref = f"{self.run_id}/{agent}/v{version}"
        payload = artifact.model_dump(by_alias=True)
        rec = ArtifactRecord(
            ref=ref,
            agent=agent,
            version=version,
            payload=payload,
            provenance=provenance or {},
        )
        with self._lock:
            self._artifacts[ref] = rec
            with self._log_path.open("a") as fh:
                fh.write(
                    json.dumps(
                        {
                            "ref": ref,
                            "agent": agent,
                            "version": version,
                            "payload": payload,
                            "provenance": rec.provenance,
                        }
                    )
                    + "\n"
                )
        return ref

    def read(self, ref: str) -> dict[str, Any]:
        """Read an artifact by ref. Raises if it doesn't exist — agents must
        not silently see missing inputs."""
        rec = self._artifacts.get(ref)
        if rec is None:
            raise KeyError(f"artifact not found: {ref}")
        return rec.payload

    def has(self, ref: str) -> bool:
        return ref in self._artifacts

    def all_refs(self) -> list[str]:
        return list(self._artifacts.keys())

    def get_record(self, ref: str) -> ArtifactRecord:
        return self._artifacts[ref]

    def provenance_chain(self, ref: str) -> list[str]:
        """Walk inputs back to roots, depth-first, deduplicated, preserves order."""
        seen: set[str] = set()
        order: list[str] = []

        def visit(r: str) -> None:
            if r in seen or r not in self._artifacts:
                return
            seen.add(r)
            for parent in self._artifacts[r].provenance.get("inputs", []):
                visit(parent)
            order.append(r)

        visit(ref)
        return order
