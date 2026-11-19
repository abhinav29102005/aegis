"""Tests for AEGIS master unified CLI."""

import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from aegis_sdk.cli import cmd_simulate, cmd_verify_chain, main


def test_cli_help(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "AEGIS" in captured.out
    assert "simulate" in captured.out
    assert "verify-chain" in captured.out


def test_cli_version(capsys):
    try:
        main(["--version"])
    except SystemExit as e:
        assert e.code == 0
    captured = capsys.readouterr()
    assert "0.1.0" in captured.out


def test_cli_verify_chain(capsys):
    ret = main(["verify-chain"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Cryptographic Merkle Event Chain Audit" in captured.out
    assert "100% VALID" in captured.out


def test_cli_simulate_compute(capsys):
    ret = main(["simulate", "--scenario", "compute", "--amount", "120.0"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Simulating Autonomous Agent Spending Cycle" in captured.out
    assert "Autonomous Cycle Succeeded" in captured.out


def test_cli_simulate_rogue(capsys):
    ret = main(["simulate", "--scenario", "rogue"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Execution Terminated" in captured.out
    assert "Velocity Cap Triggered" in captured.out


def test_cli_status_success(capsys):
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp_health = MagicMock()
        mock_resp_health.status = 200
        mock_resp_health.read.return_value = b'{"service": "aegis-api"}'
        mock_resp_health.__enter__.return_value = mock_resp_health

        mock_resp_ready = MagicMock()
        mock_resp_ready.read.return_value = b'{"status": "ready", "checks": {"database": "connected"}}'
        mock_resp_ready.__enter__.return_value = mock_resp_ready

        mock_urlopen.side_effect = [mock_resp_health, mock_resp_ready]

        ret = main(["status", "--url", "http://test-server"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "OPERATIONAL" in captured.out
