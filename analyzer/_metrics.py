from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator


def install_metrics(app: FastAPI) -> None:
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_instrument_requests_inprogress=True,
        inprogress_name="http_requests_inprogress",
        inprogress_labels=True,
        excluded_handlers=["/health", "/metrics"],
    ).instrument(app).expose(app)
