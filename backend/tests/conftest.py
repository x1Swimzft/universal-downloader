import os
import tempfile

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolate_history_file():
    """Never let the suite write into the real %LOCALAPPDATA%/UniversalDownloader history."""
    handle, path = tempfile.mkstemp(prefix="ud-history-tests-", suffix=".json")
    os.close(handle)
    previous = os.environ.get("UD_HISTORY_FILE")
    os.environ["UD_HISTORY_FILE"] = path
    try:
        yield path
    finally:
        if previous is None:
            os.environ.pop("UD_HISTORY_FILE", None)
        else:
            os.environ["UD_HISTORY_FILE"] = previous
        try:
            os.remove(path)
        except OSError:
            pass
