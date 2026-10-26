"""traceview —— 把一次模型调用的链路摊平成时间线。

设计原则：
1. **等待和计算要分开**。网络在等和模型在算，排查方式完全不同。
2. **重试要认出来**。间隔大得像重试的位置必须标出来。
3. **不接任何监控后端**。吃一份事件日志就行。

仅依赖 Python 标准库。

用法:
    python traceview.py --help
    python traceview.py --events trace.json
    python traceview.py --events trace.json --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# 阶段分类
# ---------------------------------------------------------------------------

# 事件名 → 阶段。客户端发起叫 client，服务端处理叫 server。
CLIENT_STAGES = {
    "request_start", "request_end", "serialize", "deserialize",
    "queue", "retry_wait", "backoff", "connect", "read_response",
}

SERVER_STAGES = {
    "prefill", "decode", "inference", "route", "auth", "queue_server",
    "tool_call", "postprocess", "cache_lookup",
}

NETWORK_STAGES = {
    "connect", "tls", "send", "receive", "network", "dns",
}

STAGE_LABEL = {
    "client": "客户端",
    "server": "服务端",
    "network": "网络",
    "unknown": "未分类",
}


def classify(name: str) -> str:
    """把事件名归到阶段。"""
    n = (name or "").lower()
    if n in NETWORK_STAGES:
        return "network"
    if n in SERVER_STAGES:
        return "server"
    if n in CLIENT_STAGES:
        return "client"
    # 兜底：看名字里有没有关键词
    if any(k in n for k in ("network", "connect", "tls", "dns", "socket")):
        return "network"
    if any(k in n for k in ("prefill", "decode", "infer", "model", "gpu")):
        return "server"
    if any(k in n for k in ("retry", "backoff", "wait")):
        return "client"
    return "unknown"


# ---------------------------------------------------------------------------
# 时间线
# ---------------------------------------------------------------------------

def parse_ts(value) -> float:
    """把时间戳转成 epoch 秒。支持 epoch 数字与 ISO 字符串。"""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        raise ValueError("时间戳为空")
    if s.replace(".", "", 1).isdigit():
        return float(s)
    txt = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def build_timeline(events: list[dict]) -> dict:
    """把事件列表排成时间线。"""
    rows: list[dict] = []
    for ev in events:
        name = ev.get("event") or ev.get("name") or ""
        try:
            ts = parse_ts(ev.get("ts", ev.get("timestamp", ev.get("time"))))
        except (ValueError, TypeError):
            continue
        stage = classify(name)
        duration = ev.get("duration")
        rows.append({
            "event": name,
            "ts": ts,
            "stage": stage,
            "stage_label": STAGE_LABEL[stage],
            "duration": float(duration) if isinstance(duration, (int, float)) else None,
            "detail": ev.get("detail", ""),
        })

    rows.sort(key=lambda r: r["ts"])
    if not rows:
        return {"events": [], "stages": [], "gaps": [], "suspected_retries": [],
                "total_span": 0.0, "stage_totals": {}}

    # 相邻事件之间的间隔
    gaps: list[dict] = []
    for i in range(1, len(rows)):
        gap = rows[i]["ts"] - rows[i - 1]["ts"]
        gaps.append({
            "from": rows[i - 1]["event"],
            "to": rows[i]["event"],
            "gap": round(gap, 6),
        })

    # 疑似重试：间隔明显大于其它间隔，且后一个事件名带 retry
    if len(gaps) >= 3:
        gaps_sorted = sorted(g["gap"] for g in gaps)
        median = gaps_sorted[len(gaps_sorted) // 2]
        threshold = max(median * 3, 1.0)
    else:
        median, threshold = 0.0, 1.0

    retries: list[dict] = []
    for i, g in enumerate(gaps):
        if "retry" in (g["to"] or "").lower() or "retry" in (g["from"] or "").lower():
            retries.append({**g, "reason": "事件名含 retry"})
        elif g["gap"] > threshold and threshold > 0:
            retries.append({**g, "reason": f"间隔 {g['gap']:.2f}s 超过中位数 {median:.2f}s 的三倍"})

    # 各阶段耗时
    stage_totals: dict[str, float] = {}
    for r in rows:
        if r["duration"]:
            stage_totals[r["stage"]] = stage_totals.get(r["stage"], 0.0) + r["duration"]
        else:
            # 没写 duration 的，用到下一个事件的时间差
            idx = rows.index(r)
            if idx + 1 < len(rows):
                d = rows[idx + 1]["ts"] - r["ts"]
                stage_totals[r["stage"]] = stage_totals.get(r["stage"], 0.0) + d

    total_span = rows[-1]["ts"] - rows[0]["ts"]

    return {
        "events": rows,
        "gaps": gaps,
        "suspected_retries": retries,
        "stage_totals": {k: round(v, 6) for k, v in stage_totals.items()},
        "total_span": round(total_span, 6),
        "median_gap": round(median, 6),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def render(tl: dict) -> str:
    out: list[str] = []
    if not tl["events"]:
        return "没有可用的事件。"

    out.append("调用链路时间线")
    out.append("=" * 60)
    out.append(f"事件 {len(tl['events'])} 个 ｜ 总跨度 {tl['total_span']:.3f}s"
               f" ｜ 中位间隔 {tl['median_gap']:.3f}s")
    out.append("")

    base = tl["events"][0]["ts"]
    for r in tl["events"]:
        offset = r["ts"] - base
        dur = f"  ({r['duration']:.3f}s)" if r["duration"] is not None else ""
        out.append(f"  +{offset:>8.3f}s  [{r['stage_label']:<4}] {r['event']}{dur}")
        if r["detail"]:
            out.append(f"                      {r['detail']}")

    out.append("")
    out.append("各阶段耗时：")
    for stage, total in sorted(tl["stage_totals"].items(),
                               key=lambda kv: -kv[1]):
        pct = (total / tl["total_span"] * 100) if tl["total_span"] else 0
        bar = "█" * int(pct / 2.5)
        out.append(f"  {STAGE_LABEL.get(stage, stage):<6} {total:>8.3f}s  "
                   f"{pct:>5.1f}%  {bar}")

    if tl["suspected_retries"]:
        out.append("")
        out.append("疑似重试 / 异常等待：")
        for r in tl["suspected_retries"]:
            out.append(f"  · {r['from']} → {r['to']}  间隔 {r['gap']:.3f}s"
                       f"（{r['reason']}）")
    else:
        out.append("")
        out.append("未发现疑似重试或异常等待。")
    return "\n".join(out).rstrip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="traceview",
        description="把一次模型调用的链路摊平成时间线（仅依赖标准库）",
        epilog=(
            "事件文件是 JSON 数组，每项含 event 与 ts：\n"
            "  [{\"event\":\"request_start\",\"ts\":1760000000.0},"
            "{\"event\":\"prefill\",\"ts\":1760000000.2,\"duration\":0.4}]\n"
            "  python traceview.py --events trace.json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--events", required=True, help="事件列表 JSON 文件")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    try:
        with open(args.events, "r", encoding="utf-8") as f:
            events = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"读不了事件文件：{e}", file=sys.stderr)
        return 2

    if not isinstance(events, list):
        print("事件文件应该是一个 JSON 数组。", file=sys.stderr)
        return 2

    tl = build_timeline(events)

    if args.json:
        print(json.dumps(tl, ensure_ascii=False, indent=2))
        return 0

    print(render(tl))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
