from __future__ import annotations

from workers.ai_pipeline_worker import AiPipelineWorker


def test_ai_pipeline_worker_initializes_heartbeat_state():
    worker = AiPipelineWorker()
    assert worker._heartbeat_stop is not None
    assert worker._heartbeat_thread is None
