"""Shared test bootstrap: put the bot package on sys.path and redirect all
persistent state to a temporary directory so tests never touch the repo.

Import this before importing config/db/store in tests.
"""

import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT_DIR = os.path.join(REPO_ROOT, "aria2-bot")
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

import config  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="tgdl-tests-")
config.BASE_DIR = _TMP
config.DOWNLOAD_DIR = os.path.join(_TMP, "downloads")
config.CHANNEL_ID = -100123
config.OWNER_ID = 1
config.CACHE_TTL_DAYS = 7

TEST_TMP = _TMP
