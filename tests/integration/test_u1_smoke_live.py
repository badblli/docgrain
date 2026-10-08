"""Explicit opt-in only: creates a workspace and sends synthetic content to a model."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get("DOCGRAIN_U1_SMOKE_LIVE") != "1",
                    reason="Canlı U1 yürüyüşü için DOCGRAIN_U1_SMOKE_LIVE=1 gerekli.")
def test_u1_smoke_live(tmp_path):
    options = {"--api": "DOCGRAIN_U1_API", "--credential-id": "DOCGRAIN_U1_CREDENTIAL_ID",
               "--base-url": "DOCGRAIN_U1_BASE_URL", "--model": "DOCGRAIN_U1_MODEL"}
    missing = [name for name in options.values() if not os.environ.get(name)]
    assert not missing, "Canlı yürüyüş ayarları eksik: " + ", ".join(missing)
    script = Path(__file__).resolve().parents[2] / "docs/examples/u1_smoke.py"
    command = [sys.executable, "-X", "utf8", str(script), "--live", "--out", str(tmp_path)]
    for flag, variable in options.items():
        command.extend([flag, os.environ[variable]])
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                            timeout=2400, check=False)
    # The script reports only safe, local reasons. Never include a subprocess traceback/body.
    assert (tmp_path / "report.json").exists(), "Yürüyüş raporu oluşturulmadı."
    assert result.returncode == 0, result.stdout
