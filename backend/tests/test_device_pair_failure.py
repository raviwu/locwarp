"""Tests for surfacing devices that fail USB lockdown pair validation."""

import pytest

from core.device_manager import _classify_pair_error


class _FakePairingPending(Exception):
    """Stand-in for pymobiledevice3.exceptions.PairingDialogResponsePendingError."""


class _FakeNotPaired(Exception):
    """Stand-in for pymobiledevice3.exceptions.PairingError ('not paired')."""


@pytest.mark.parametrize(
    "exc,expected_status,expected_substring",
    [
        # ConnectionTerminatedError is the most common signal for a stale
        # pair record (iPhone has forgotten this host). Mapped to "trust_required".
        (ConnectionResetError("Connection terminated"), "trust_required", "重新信任"),
        # PairingDialogResponsePending: user hasn't tapped Trust yet.
        (_FakePairingPending("PairingDialogResponsePending"), "trust_required", "信任"),
        # "not paired" text from PairingError variants.
        (_FakeNotPaired("device is not paired with this host"), "trust_required", "USB"),
        # Anything else falls through to "error" with the raw message.
        (RuntimeError("unexpected backend explosion"), "error", "unexpected backend explosion"),
    ],
)
def test_classify_pair_error_maps_known_signals(exc, expected_status, expected_substring):
    status, message = _classify_pair_error(exc)
    assert status == expected_status
    assert expected_substring in message


def test_classify_pair_error_trims_long_message():
    long = "x" * 500
    status, message = _classify_pair_error(RuntimeError(long))
    assert status == "error"
    assert len(message) <= 200
