"""
Crash-safe scan-state persistence for multi-pass Interpol sweeps.
ScanStateManager — persists pass progress to a JSON file on the shared
    Docker volume (/data/scan_state.json).  On restart the fetcher reads
    this file and resumes from where it left off (crash-safe).

PassContext — immutable descriptor for a single sweep pass; created once
    at pass start and threaded through sub-calls so every log line carries
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ScanStateManager:
    """Persists pass progress to a JSON file (atomic write) so scans survive restarts."""

    def __init__(self, state_file: str) -> None:
        self.state_file = state_file
        self._state = self._load()

    def is_pass_done(self, pass_name: str) -> bool:
        return pass_name in self._state["completed_passes"]

    def get_resume_idx(self, pass_name: str) -> int:
        # Returns nonzero only when we crashed mid-pass and need to skip already-done queries.
        if self._state.get("current_pass") == pass_name:
            return self._state.get("current_query_idx", 0)
        return 0

    def mark_query_progress(self, pass_name: str, query_idx: int) -> None:
        self._state["current_pass"] = pass_name
        self._state["current_query_idx"] = query_idx
        self._save()

    def mark_pass_done(self, pass_name: str) -> None:
        if pass_name not in self._state["completed_passes"]:
            self._state["completed_passes"].append(pass_name)
        self._state["current_pass"] = None
        self._state["current_query_idx"] = 0
        self._save()
        logger.info("Pass '%s' done; state saved to %s", pass_name, self.state_file)

    def reset(self) -> None:
        """Clear all state to force a fresh full scan on next run."""
        self._state = {"completed_passes": [], "current_pass": None, "current_query_idx": 0}
        self._save()

    def _load(self) -> Dict[str, Any]:
        try:
            with open(self.state_file, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"completed_passes": [], "current_pass": None, "current_query_idx": 0}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
            tmp = self.state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2)
            os.replace(tmp, self.state_file)
        except OSError as exc:
            logger.warning("State file write failed: %s", exc)


@dataclass
class PassContext:
    """Immutable descriptor for a single sweep pass, threaded through sub-calls for consistent logging."""
    pass_id: str
    name: str
    combo_total: int
    state_file: str = "<none>"
