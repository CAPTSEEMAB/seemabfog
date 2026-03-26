"""
Local Spool Store — Store-and-Forward for Fog Node
Persists outgoing messages to disk (JSONL) when SQS is unreachable,
then replays them when connectivity is restored.
"""

import json
import os
import glob
import time
import asyncio
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class SpoolFlushError(Exception):
    """Raised when SQS is still unreachable during flush."""
    pass


class LocalSpoolStore:
    """
    Disk-backed JSONL spool for store-and-forward.

    Each line in a spool file is:
        {"type": "aggregate"|"event", "payload": "<json>",
         "key": "<idempotency_key>", "enqueued_at": "<iso>"}

    File naming: {message_type}_{YYYYMMDD_HHMMSS}_{seq}.jsonl
    Rotation:    New file every MAX_LINES_PER_FILE lines or ROTATION_INTERVAL_SEC.
    Limits:      Max MAX_SPOOL_FILES files; oldest deleted on overflow.
    """

    MAX_LINES_PER_FILE = 1000
    MAX_SPOOL_FILES = 100
    ROTATION_INTERVAL_SEC = 60

    def __init__(self, spool_dir: str = "spool_data/"):
        self.spool_dir = spool_dir
        os.makedirs(self.spool_dir, exist_ok=True)
        self._current_file = None
        self._current_lines = 0
        self._current_file_opened_at = time.monotonic()
        self._sequence = 0
        self._lock = asyncio.Lock()
        logger.info(f"Spool store initialised: {self.spool_dir}")

    # ── Public API ──────────────────────────────────────────────

    def enqueue(self, message_type: str, payload: str, idempotency_key: str,
                 junction_id: str = "unknown") -> None:
        """
        Append one message to the current spool file (synchronous).
        Thread-safe when called from a single asyncio event loop.
        """
        self._ensure_file_open(message_type)

        line = json.dumps({
            "type": message_type,
            "idempotency_key": idempotency_key,
            "junctionId": junction_id,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "payload": payload
        })

        self._current_file.write(line + "\n")
        self._current_file.flush()
        self._current_lines += 1

        # Rotate if needed
        if self._current_lines >= self.MAX_LINES_PER_FILE:
            self._rotate_file()

        # Enforce file count limit
        self._enforce_limits()

    async def flush_to_sqs(self, sqs_client, agg_queue_url: str, evt_queue_url: str) -> int:
        """
        Read spool files oldest-first and send to SQS.
        Returns count of messages successfully flushed.
        Raises SpoolFlushError on first SQS failure (stop early).
        """
        flushed = 0
        spool_files = self._list_spool_files()

        for filepath in spool_files:
            remaining_lines = []
            try:
                with open(filepath, "r") as f:
                    lines = f.readlines()
            except FileNotFoundError:
                continue

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(f"Skipping corrupt spool line: {line[:80]}")
                    continue

                msg_type = record["type"]
                payload = record["payload"]
                idem_key = record.get("idempotency_key") or record.get("key", "")

                queue_url = agg_queue_url if msg_type == "aggregate" else evt_queue_url

                # Extract junction ID from payload for MessageGroupId
                try:
                    payload_obj = json.loads(payload)
                    group_id = payload_obj.get("junctionId", "unknown")
                except (json.JSONDecodeError, TypeError):
                    group_id = "unknown"

                try:
                    sqs_client.send_message(
                        QueueUrl=queue_url,
                        MessageBody=payload,
                        MessageGroupId=group_id,
                        MessageDeduplicationId=idem_key
                    )
                    flushed += 1
                except Exception as e:
                    # SQS still down — keep remaining lines and stop
                    remaining_lines.append(line + "\n")
                    remaining_lines.extend(
                        l for l in lines[lines.index(line + "\n") + 1:]
                        if l.strip()
                    )
                    # Write back remaining
                    with open(filepath, "w") as f:
                        f.writelines(remaining_lines)
                    raise SpoolFlushError(
                        f"SQS still unreachable after flushing {flushed} messages: {e}"
                    )

            # All lines in this file flushed successfully — delete file
            try:
                os.remove(filepath)
                logger.info(f"Spool file flushed and removed: {filepath}")
            except OSError:
                pass

        return flushed

    def spool_size(self) -> int:
        """Return total number of un-flushed messages across all spool files."""
        total = 0
        for filepath in self._list_spool_files():
            try:
                with open(filepath, "r") as f:
                    total += sum(1 for line in f if line.strip())
            except (FileNotFoundError, OSError):
                pass
        return total

    def spool_bytes(self) -> int:
        """Return total bytes on disk across all spool files."""
        total = 0
        for filepath in self._list_spool_files():
            try:
                total += os.path.getsize(filepath)
            except (FileNotFoundError, OSError):
                pass
        return total

    def oldest_created_at(self) -> Optional[str]:
        """Return created_at of the oldest un-flushed record, or None."""
        for filepath in self._list_spool_files():
            try:
                with open(filepath, "r") as f:
                    for raw_line in f:
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        record = json.loads(raw_line)
                        return record.get("created_at") or record.get("enqueued_at")
            except (FileNotFoundError, OSError, json.JSONDecodeError):
                continue
        return None

    # ── Internal Helpers ────────────────────────────────────────

    def _ensure_file_open(self, message_type: str) -> None:
        """Open a spool file if none is open, or rotate if interval elapsed."""
        elapsed = time.monotonic() - self._current_file_opened_at
        if self._current_file is None or elapsed > self.ROTATION_INTERVAL_SEC:
            self._rotate_file()
            self._open_new_file(message_type)

    def _open_new_file(self, message_type: str = "mixed") -> None:
        """Open a new spool file with timestamp + sequence naming."""
        self._sequence += 1
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{message_type}_{ts}_{self._sequence:04d}.jsonl"
        filepath = os.path.join(self.spool_dir, filename)
        self._current_file = open(filepath, "a")
        self._current_lines = 0
        self._current_file_opened_at = time.monotonic()

    def _rotate_file(self) -> None:
        """Close current file handle."""
        if self._current_file is not None:
            try:
                self._current_file.close()
            except Exception:
                pass
            self._current_file = None

    def _list_spool_files(self) -> list:
        """Return sorted list of spool file paths (oldest first)."""
        pattern = os.path.join(self.spool_dir, "*.jsonl")
        files = glob.glob(pattern)
        files.sort()  # Lexicographic sort = chronological by timestamp
        return files

    def _enforce_limits(self) -> None:
        """Delete oldest spool files if count > MAX_SPOOL_FILES."""
        files = self._list_spool_files()
        while len(files) > self.MAX_SPOOL_FILES:
            oldest = files.pop(0)
            try:
                os.remove(oldest)
                logger.warning(f"Spool limit exceeded — deleted oldest: {oldest}")
            except OSError:
                pass
