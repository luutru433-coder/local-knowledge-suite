# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import time
import threading
import uuid

from .pipeline import KnowledgeService


def run_worker(service: KnowledgeService, poll_seconds: float = 2.0, once: bool = False) -> int:
    processed = 0
    worker_id = f"worker-{uuid.uuid4().hex[:12]}"
    while True:
        job = service.lease_job(worker_id=worker_id)
        if job is None:
            if once:
                return processed
            time.sleep(poll_seconds)
            continue
        stop = threading.Event()

        def renew() -> None:
            while not stop.wait(service.settings.heartbeat_seconds):
                if not service.heartbeat_job(int(job["id"]), str(job["lease_token"])):
                    return

        heartbeat = threading.Thread(target=renew, name=f"ckb-heartbeat-{job['id']}", daemon=True)
        heartbeat.start()
        try:
            service.run_job(int(job["id"]), lease_token=str(job["lease_token"]), worker_id=worker_id)
        except Exception:
            pass
        finally:
            stop.set()
            heartbeat.join(timeout=2)
        processed += 1
        if once:
            return processed
