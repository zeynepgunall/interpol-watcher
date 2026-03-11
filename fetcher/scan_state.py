"""Crash-safe tarama durumu yönetimi.

ScanStateManager — pass ilerlemesini JSON dosyasına kaydeder.
Fetcher yeniden başladığında kaldığı yerden devam eder.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class ScanStateManager:
    """Pass ilerlemesini JSON dosyasına kaydeder."""

    def __init__(self, state_file: str) -> None:
        self.state_file = state_file
        self._state = self._load()

    def is_pass_done(self, pass_name: str) -> bool:
        return pass_name in self._state["completed_passes"] #bu pass daha önce tamamen bitti mi?


    def get_resume_idx(self, pass_name: str) -> int:
        """restart olduğunda kaldığı yerden devam ediyor"""
        if self._state.get("current_pass") == pass_name:
            return self._state.get("current_query_idx", 0)
        return 0
    
    def mark_query_progress(self, pass_name: str, query_idx: int) -> None:
        """her sorgudan sonra ilerlemeyi kaydediyor"""
        self._state["current_pass"] = pass_name
        self._state["current_query_idx"] = query_idx
        self._save()

    def mark_pass_done(self, pass_name: str) -> None:
        """bir pass bittiğinde işaretliyor"""
        if pass_name not in self._state["completed_passes"]:
            self._state["completed_passes"].append(pass_name)
        self._state["current_pass"] = None
        self._state["current_query_idx"] = 0
        self._save()
        logger.info("Pass '%s' tamamlandı; state kaydedildi: %s", pass_name, self.state_file)

    def reset(self) -> None:
        """Tüm state'ı sıfırlar — bir sonraki çalıştırmada baştan taranır."""
        self._state = {"completed_passes": [], "current_pass": None, "current_query_idx": 0}
        self._save()

#
    def _load(self) -> dict[str, Any]:
        """State dosyasını okur; dosya yoksa veya bozuksa boş state döndürür."""
        try:
            with open(self.state_file, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"completed_passes": [], "current_pass": None, "current_query_idx": 0}

    def _save(self) -> None:
        """Geçici dosyaya yazıp atomik rename(geçici dosyaya yazma) ile asıl dosyaya taşır (crash-safe)."""
        try:
            os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
            tmp = self.state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2)
            os.replace(tmp, self.state_file)
        except OSError as exc:
            logger.warning("State dosyası yazılamadı: %s", exc)
