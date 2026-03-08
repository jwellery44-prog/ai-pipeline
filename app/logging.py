import json
import logging
import sys
from datetime import datetime

from app.config import settings


class JSONFormatter(logging.Formatter):
    # JSON lines format makes it easy to stream logs into Datadog, CloudWatch,
    # or any log aggregator without additional parsing rules.
    def format(self, record):
        log_obj = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
        }
        # Callers can attach extra context like job_id by passing it via extra={}
        if hasattr(record, "job_id"):
            log_obj["job_id"] = record.job_id
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


def setup_logging():
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    # Replace any handlers that might have been set by imported libraries.
    root.handlers = [handler]

    # httpx is noisy at DEBUG/INFO — suppress it so our own logs stay readable.
    logging.getLogger("httpx").setLevel(logging.WARNING)


setup_logging()
logger = logging.getLogger(__name__)
