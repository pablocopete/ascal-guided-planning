"""Smoke tests for the KEPS experiment pipeline."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

EXP_ROOT = Path(__file__).resolve().parent.parent   # .../experiments/KEPS2026
REPO = EXP_ROOT.parent.parent                        # project root (KEPS/)
SCRIPTS = EXP_ROOT / "scripts"


def _load_agg() -> object:
    """Dynamically load aggregate_results_server from scripts/."""
    agg_py = SCRIPTS / "aggregate_results_server.py"
    spec = importlib.util.spec_from_file_location("aggregate_results_server", agg_py)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["aggregate_results_server"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_ascal_importable() -> None:
    """The ascal package must be importable in the active environment."""
    import ascal  # noqa: F401
    from ascal import Learner  # noqa: F401
    from ascal.evaluation import compute_version_space_size  # noqa: F401


def test_parse_log_on_sample() -> None:
    """parse_log must extract key fields from a real result log."""
    agg = _load_agg()
    sample_log = next((EXP_ROOT / "results" / "results_ascal_no_restart").glob("*/*.log"), None)
    if sample_log is None:
        import pytest
        pytest.skip("results/results_ascal_no_restart logs not present")

    text = sample_log.read_text(encoding="utf-8", errors="replace")
    data = agg.parse_log(text)

    assert "start_utc" in data, "parse_log must return start_utc"
    assert "sound_success_gt" in data, "parse_log must return sound_success_gt"


def test_scripts_importable() -> None:
    """Experiment scripts must be importable without errors."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        import ucs_baseline_core  # noqa: F401
    finally:
        sys.path.pop(0)
