from __future__ import annotations

import logging
import os


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", level).upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("py4j").setLevel(logging.WARNING)
