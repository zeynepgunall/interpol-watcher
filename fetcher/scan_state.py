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
from typing import Any

logger = logging.getLogger(__name__)


class ScanStateManager:
    """Persists pass progress to a JSON file (atomic write) so scans survive restarts."""

    def __init__(self, state_file: str) -> None:
        """Verilen dosya yolundan mevcut durumu yükler; dosya yoksa boş durumla başlar."""
        self.state_file = state_file
        self._state = self._load()

    def is_pass_done(self, pass_name: str) -> bool:
        """Belirtilen pass'ın daha önce tamamlanıp tamamlanmadığını kontrol eder."""
        return pass_name in self._state["completed_passes"]

    def get_resume_idx(self, pass_name: str) -> int:
        """Crash sonrası kaldığı yerden devam için son kaydedilen query indeksini döndürür."""
        # Returns nonzero only when we crashed mid-pass and need to skip already-done queries.
        if self._state.get("current_pass") == pass_name:
            return self._state.get("current_query_idx", 0)
        return 0

    def mark_query_progress(self, pass_name: str, query_idx: int) -> None:
        """Aktif pass adı ve query indeksini state dosyasına atomik olarak kaydeder."""
        self._state["current_pass"] = pass_name
        self._state["current_query_idx"] = query_idx
        self._save()

    def mark_pass_done(self, pass_name: str) -> None:
        """Pass'ı tamamlanmış olarak işaretler, ilerlemeyi sıfırlar ve diske yazar."""
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

    def _load(self) -> dict[str, Any]:
        """State dosyasını JSON olarak okur; dosya yoksa veya bozuksa boş state döndürür."""
        try:
            with open(self.state_file, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"completed_passes": [], "current_pass": None, "current_query_idx": 0}

    def _save(self) -> None:
        """State'ı geçici dosyaya yazıp atomik rename ile asıl dosyaya taşır (crash-safe)."""
        try:
            os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
            tmp = self.state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2)
            os.replace(tmp, self.state_file)
        except OSError as exc:
            logger.warning("State file write failed: %s", exc)
