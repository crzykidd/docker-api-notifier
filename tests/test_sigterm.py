import signal

import pytest

import main


def test_sigterm_handler_exits_cleanly():
    with pytest.raises(SystemExit) as exc:
        main._handle_sigterm(signal.SIGTERM, None)
    assert exc.value.code == 0
