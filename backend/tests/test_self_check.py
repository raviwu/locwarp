"""The --self-check import chain must (a) cover every native-chain module
documented in locwarp-backend.spec, (b) succeed in the dev venv (the same
chain the DMG ships), and (c) report a non-zero exit on the first failure.

Cross-checking the list against the .spec catches drift between the spec's
enumerated metadata fixes and what the self-check actually probes.
"""
from __future__ import annotations

import io
from pathlib import Path

import self_check

SPEC_PATH = Path(__file__).resolve().parent.parent / "locwarp-backend.spec"

# The native packages the .spec bundles metadata/binaries for, that the
# self-check is responsible for proving importable. (developer_disk_image is
# data-only — no import-time metadata.version() call — so it is NOT in the
# self-check; numpy is pulled in transitively by timezonefinder/h3.)
SPEC_GUARDED_PACKAGES = ["pyimg4", "apple_compress", "prompt_toolkit", "h3", "timezonefinder"]


def test_chain_is_ordered_tuples_of_label_and_module():
    assert isinstance(self_check.NATIVE_IMPORT_CHAIN, list)
    for entry in self_check.NATIVE_IMPORT_CHAIN:
        assert isinstance(entry, tuple) and len(entry) == 2
        label, module = entry
        assert isinstance(label, str) and label
        assert isinstance(module, str) and module


def test_every_spec_guarded_package_is_probed():
    """Each package the .spec spends a copy_metadata/collect_all on must appear
    as a probed module in the self-check chain — else a metadata gap could
    reappear undetected."""
    probed = {module for _label, module in self_check.NATIVE_IMPORT_CHAIN}
    for pkg in SPEC_GUARDED_PACKAGES:
        assert any(pkg == m or m.endswith(pkg) or m.split(".")[0] == pkg for m in probed), (
            f"{pkg} is metadata-bundled in the .spec but not probed by self_check"
        )


def test_spec_actually_references_each_guarded_package():
    """Guard the cross-check from the other side: if someone deletes a
    copy_metadata line from the .spec, this fails so the pairing stays honest."""
    spec_text = SPEC_PATH.read_text("utf-8")
    for pkg in SPEC_GUARDED_PACKAGES:
        assert pkg in spec_text, f"{pkg} no longer referenced in locwarp-backend.spec"


def test_run_self_check_passes_in_dev_venv():
    out = io.StringIO()
    rc = self_check.run_self_check(out=out)
    assert rc == 0, out.getvalue()
    assert "SELF-CHECK OK" in out.getvalue()


def test_run_self_check_reports_first_failure(monkeypatch):
    """A missing module makes run_self_check return 1 and name the offender."""
    import importlib

    real_import = importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name == "apple_compress":
            raise ModuleNotFoundError("No module named 'apple_compress'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(self_check.importlib, "import_module", fake_import)
    out = io.StringIO()
    rc = self_check.run_self_check(out=out)
    assert rc == 1
    assert "SELF-CHECK FAILED" in out.getvalue()
    assert "apple_compress" in out.getvalue()
