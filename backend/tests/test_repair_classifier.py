"""Unit tests for ``_classify_repair_error`` in api.device."""

from api.device import _classify_repair_error


def test_utun_wins_over_generic_fallback():
    msg = "[Errno 0] Failed to create any utun interface"
    out = _classify_repair_error(msg)
    assert "utun" in out
    assert "管理員" in out


def test_trust_dialog_branch():
    msg = "PairingDialogResponsePending — waiting for user consent"
    out = _classify_repair_error(msg)
    assert "信任" in out


def test_pairing_error_branch():
    msg = "PairingError: not paired"
    out = _classify_repair_error(msg)
    assert "USB" in out and "信任" in out


def test_consent_lowercase_match():
    out = _classify_repair_error("pairing consent timeout")
    assert "信任" in out


def test_generic_fallback_includes_raw_message():
    out = _classify_repair_error("something exotic happened")
    assert "RemotePairing 握手失敗" in out
    assert "something exotic happened" in out


def test_utun_classification_outranks_other_branches():
    # An error mentioning both utun and pairing should pick utun — privilege
    # is the actionable root cause; Trust prompt wouldn't help.
    out = _classify_repair_error("PairingError: not paired; also Failed to create utun")
    assert "utun" in out
