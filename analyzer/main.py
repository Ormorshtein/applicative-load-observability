import os

from fastapi import FastAPI

from ._logging import configure_logging
from ._metrics import install_metrics
from ._routes import register_routes

# Must run before FastAPI/Instrumentator so all log records use our format.
configure_logging()

app = FastAPI()
install_metrics(app)
register_routes(app)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "analyzer.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        log_config=None,  # preserve our dictConfig; uvicorn.run() would overwrite it otherwise
    )


if __name__ == "__main__":
    main()
