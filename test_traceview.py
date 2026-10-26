"""traceview —— 自检测试。

把调用事件按阶段排成时间线，标出最慢的环节与可能的重试。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import traceview  # noqa: E402


class TestTraceView(unittest.TestCase):
    def setUp(self):
        self.events = [
            {"event": "request_start", "ts": 1000.0},
            {"event": "connect", "ts": 1000.1},
            {"event": "prefill", "ts": 1000.2, "duration": 0.3},
            {"event": "decode", "ts": 1000.5, "duration": 1.0},
            {"event": "request_end", "ts": 1001.5},
        ]

    def test_timeline_is_sorted(self):
        tl = traceview.build_timeline(self.events)
        self.assertEqual(tl["events"][0]["event"], "request_start")
        self.assertEqual(tl["events"][-1]["event"], "request_end")

    def test_stages_are_classified(self):
        tl = traceview.build_timeline(self.events)
        by_name = {e["event"]: e["stage"] for e in tl["events"]}
        self.assertEqual(by_name["prefill"], "server")
        self.assertEqual(by_name["connect"], "network")

    def test_stage_totals_are_reported(self):
        tl = traceview.build_timeline(self.events)
        self.assertIn("server", tl["stage_totals"])
        self.assertGreater(tl["total_span"], 0)

    def test_retry_is_detected(self):
        events = [
            {"event": "request_start", "ts": 1000.0},
            {"event": "request_end", "ts": 1000.5},
            {"event": "retry", "ts": 1010.0},
            {"event": "request_end", "ts": 1010.5},
        ]
        tl = traceview.build_timeline(events)
        self.assertTrue(tl["suspected_retries"])

    def test_empty_events(self):
        tl = traceview.build_timeline([])
        self.assertEqual(tl["events"], [])
