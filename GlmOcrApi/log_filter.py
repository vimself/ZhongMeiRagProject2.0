#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime


NCCL_TCPSTORE_PATTERNS = (
    re.compile(
        r'ProcessGroupNCCL\.cpp:\d+.*Failed to check the "should dump" flag on TCPStore.*Broken pipe'
    ),
    re.compile(r"TCPStore\.cpp:\d+.*sendBytes failed.*Broken pipe"),
    re.compile(r"Exception raised from sendBytes at .*/c10d/Utils\.hpp"),
)
STACK_FRAME_PATTERN = re.compile(r"^\s*(?:\[rank\d+\]:\s*)?frame #\d+:")


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


class LogFilter:
    def __init__(self, source: str, filter_nccl_broken_pipe: bool, summary_interval: int) -> None:
        self.source = source
        self.filter_nccl_broken_pipe = filter_nccl_broken_pipe
        self.summary_interval = max(summary_interval, 0)
        self.suppressing_stack = False
        self.suppressed_count = 0
        self.last_summary_at = 0.0

    def process(self, line: str) -> str | None:
        if not self.filter_nccl_broken_pipe:
            return line

        if self.suppressing_stack:
            if line.strip() == "" or STACK_FRAME_PATTERN.search(line):
                self._record_suppressed()
                return None
            self.suppressing_stack = False

        if any(pattern.search(line) for pattern in NCCL_TCPSTORE_PATTERNS):
            self._record_suppressed()
            if "Exception raised from sendBytes" in line:
                self.suppressing_stack = True
            return None

        return line

    def _record_suppressed(self) -> None:
        self.suppressed_count += 1
        if self.summary_interval <= 0:
            return
        now = time.monotonic()
        if self.last_summary_at and now - self.last_summary_at < self.summary_interval:
            return
        self.last_summary_at = now
        ts = datetime.now().astimezone().isoformat()
        print(
            f"{ts} log_filter source={self.source} "
            f"suppressed=torch_distributed_tcpstore_broken_pipe count={self.suppressed_count}",
            flush=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Filter noisy GLM-OCR runtime logs.")
    parser.add_argument("--source", default="glm-ocr")
    args = parser.parse_args()

    log_filter = LogFilter(
        source=args.source,
        filter_nccl_broken_pipe=_bool_env("GLM_LOG_FILTER_NCCL_BROKEN_PIPE", True),
        summary_interval=_int_env("GLM_LOG_FILTER_SUMMARY_INTERVAL_SECONDS", 600),
    )
    for line in sys.stdin:
        filtered = log_filter.process(line)
        if filtered is None:
            continue
        print(filtered, end="", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
