"""Dedicated durable WhatsApp dispatcher: python -m app.whatsapp_runner.

No external request is retried after its durable 'sending' boundary.
"""
import asyncio
import logging
from pathlib import Path

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.whatsapp_service import configured, dispatch_one

logger = logging.getLogger(__name__)


async def run_forever():
    while True:
        if configured():
            try:
                async with AsyncSessionLocal() as db:
                    await dispatch_one(db)
                Path('/tmp/whatsapp-dispatcher.health').touch()
            except Exception:
                # Do not log provider bodies, invitation tokens or credentials.
                logger.error('WhatsApp dispatch tick failed; persisted jobs retained', exc_info=False)
        else:
            Path('/tmp/whatsapp-dispatcher.health').touch()
        await asyncio.sleep(max(2, min(30, get_settings().whatsapp_dispatch_interval_seconds)))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
