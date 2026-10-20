import os
import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


async def cleanup_old_files(tmp_dir: str, max_age_minutes: int = 15):
    """Delete files in tmp_dir older than max_age_minutes."""
    now = datetime.now()
    try:
        for fname in os.listdir(tmp_dir):
            fpath = os.path.join(tmp_dir, fname)
            if not os.path.isfile(fpath):
                continue
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if now - mtime > timedelta(minutes=max_age_minutes):
                os.remove(fpath)
                logger.info(f"Purged: {fname}")
    except Exception as e:
        logger.error(f"Cleanup error: {e}")
