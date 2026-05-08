import logging
import logging.config
import os


def configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
            },
        },
        "handlers": {
            "stderr": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
                "formatter": "default",
            },
        },
        "root": {
            "handlers": ["stderr"],
            "level": level,
        },
        # uvicorn logs propagate to root; suppress the access log to avoid
        # double-emission while keeping error logs.
        "loggers": {
            "uvicorn.error": {"propagate": True},
            "uvicorn.access": {"propagate": False},
        },
    })
