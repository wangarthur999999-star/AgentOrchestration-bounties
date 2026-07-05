"""CodeSage entry point — starts the webhook server."""

import logging
import sys

import uvicorn

from src.codesage.config import CodeSageConfig
from src.common.logging import configure_logging


def main() -> int:
    configure_logging("INFO")
    logger = logging.getLogger(__name__)

    config = CodeSageConfig()
    issues = config.validate()
    if issues:
        for issue in issues:
            logger.error(f"Configuration error: {issue}")
        return 1

    logger.info(f"Starting CodeSage v{__import__('src.codesage').__version__}")
    logger.info(f"Listening on {config.host}:{config.port}")

    uvicorn.run(
        "src.codesage.server:app",
        host=config.host,
        port=config.port,
        log_level="info",
        reload=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
