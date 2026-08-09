from .command import run_command_check
from .file import run_file_check
from .http import run_http_check
from .json_check import run_json_check
from .metric import run_metric_check
from .tcp import run_tcp_check

CHECK_RUNNERS = {
    "file": run_file_check,
    "json": run_json_check,
    "metric": run_metric_check,
    "http": run_http_check,
    "tcp": run_tcp_check,
    "command": run_command_check,
}
