"""Standalone process entrypoint for overdue-task notifications.

Run with: python -m app.scheduler_runner
"""
import asyncio
import logging

from app.services.task_scheduler import run_forever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
