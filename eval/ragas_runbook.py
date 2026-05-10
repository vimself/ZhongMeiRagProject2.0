"""Stage 7 RAG 评测 Runbook.

本脚本用于对 RAG 问答链路进行离线评测，可选依赖 ragas；若未安装
ragas 或未配置外部 LLM key，则使用内置的「关键字命中 + 引用覆盖」
启发式指标，保证无外部密钥时也能跑通。

评测结果会落到 ``rag_eval_runs`` 表，便于后续趋势跟踪。

使用方式::

    python -m eval.ragas_runbook --kb-id <kb_uuid> --user-id <user_uuid> \
        --golden eval/golden_cases.json --run-key stage7-smoke

若仅想查看本地启发式指标而不写库，可添加 ``--dry-run``。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


async def _run_single_case(
    *,
    case: dict[str, Any],
    kb_id: str,
    user_id: str,
) -> dict[str, Any]:
    """对单条金标运行 RAG 图，返回 answer + citations + 指标."""

    from app.db.session import AsyncSessionLocal
    from app.services.llm.client import DashScopeClient
    from app.services.rag.graph import (
        fallback_no_hit_stream,
        generate_stream,
        prepare_citations,
        rewrite_citations,
    )

    question = case["question"]
    query_vector: list[float] | None = None
    try:
        async with DashScopeClient() as client:
            embeddings = await client.embed_batch([question])
        query_vector = embeddings[0] if embeddings else None
    except Exception:
        query_vector = None

    async with AsyncSessionLocal() as db:
        state = await prepare_citations(
            db,
            user_id=user_id,
            kb_id=kb_id,
            query=question,
            query_vector=query_vector,
        )

    chunks = []
    if state.has_hit:
        async for token in generate_stream(state):
            chunks.append(token)
        state.answer_raw = "".join(chunks)
        state.answer_rewritten = rewrite_citations(state.answer_raw, state)
    else:
        async for token in fallback_no_hit_stream():
            chunks.append(token)
        state.answer_raw = "".join(chunks)
        state.answer_rewritten = state.answer_raw
    answer = state.answer_rewritten or state.answer_raw

    hits = _keyword_hits(
        answer=answer,
        citations=state.citations,
        keywords=case.get("expected_citations_keywords") or [],
    )
    return {
        "id": case["id"],
        "question": question,
        "reference_answer": case.get("reference_answer", ""),
        "answer": answer,
        "citations": [asdict(c) for c in state.citations],
        "has_hit": bool(state.has_hit),
        "metrics": {
            "keyword_hit_ratio": hits,
            "citation_count": len(state.citations),
        },
    }


def _keyword_hits(*, answer: str, citations: list[Any], keywords: list[str]) -> float:
    """启发式命中率：回答或引用 snippet 中命中关键字的比例."""

    if not keywords:
        return 1.0
    blob = answer
    for c in citations:
        snippet = getattr(c, "snippet", None) or (
            c.get("snippet") if isinstance(c, dict) else ""
        )
        blob += "\n" + (snippet or "")
    hit = sum(1 for kw in keywords if kw.lower() in blob.lower())
    return round(hit / len(keywords), 4)


def _try_ragas(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """可选 ragas 指标；失败时返回 None."""
    try:  # pragma: no cover - optional path
        from ragas import evaluate  # type: ignore
        from ragas.metrics import answer_relevancy, faithfulness  # type: ignore
        from datasets import Dataset  # type: ignore
    except Exception:
        return None
    try:  # pragma: no cover - optional path
        dataset = Dataset.from_list(
            [
                {
                    "question": r["question"],
                    "answer": r["answer"],
                    "contexts": [c.get("snippet", "") for c in r["citations"]],
                    "ground_truth": r["reference_answer"],
                }
                for r in results
            ]
        )
        report = evaluate(dataset, metrics=[faithfulness, answer_relevancy])
        return {k: float(v) for k, v in report.items()}
    except Exception as exc:  # pragma: no cover - optional
        return {"error": f"ragas 运行失败：{exc}"}


async def _persist_run(
    *,
    run_key: str,
    golden_file: str,
    summary: dict[str, Any],
    metrics: dict[str, Any],
) -> str:
    from app.db.session import AsyncSessionLocal
    from app.models.chat import RagEvalRun

    async with AsyncSessionLocal() as db:
        row = RagEvalRun(
            run_key=run_key,
            golden_file=golden_file,
            summary_json=summary,
            metrics_json=metrics,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def main_async(args: argparse.Namespace) -> int:
    golden_path = Path(args.golden).resolve()
    if not golden_path.exists():
        print(f"[ERROR] 金标文件不存在：{golden_path}")
        return 2
    cases = json.loads(golden_path.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        print("[ERROR] 金标文件格式应为数组")
        return 2

    print(f"[info] 金标条数：{len(cases)}；知识库：{args.kb_id}")
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    for i, case in enumerate(cases, 1):
        t0 = time.perf_counter()
        try:
            item = await _run_single_case(
                case=case, kb_id=args.kb_id, user_id=args.user_id
            )
        except Exception as exc:  # pragma: no cover - defensive
            item = {
                "id": case.get("id"),
                "question": case.get("question"),
                "error": str(exc),
                "metrics": {"keyword_hit_ratio": 0.0, "citation_count": 0},
                "has_hit": False,
            }
        dt = time.perf_counter() - t0
        item["elapsed_sec"] = round(dt, 3)
        print(
            f"[{i:02d}/{len(cases)}] {case.get('id')} "
            f"hit={item.get('has_hit')} kw={item['metrics']['keyword_hit_ratio']} "
            f"cite={item['metrics']['citation_count']} t={dt:.2f}s"
        )
        results.append(item)

    total_sec = round(time.perf_counter() - started, 3)
    avg_kw = round(
        sum(r["metrics"]["keyword_hit_ratio"] for r in results) / max(1, len(results)),
        4,
    )
    coverage = round(
        sum(1 for r in results if r.get("has_hit")) / max(1, len(results)), 4
    )
    avg_cite = round(
        sum(r["metrics"]["citation_count"] for r in results) / max(1, len(results)), 3
    )

    summary = {
        "cases": len(results),
        "total_sec": total_sec,
        "hit_coverage": coverage,
        "avg_keyword_hit": avg_kw,
        "avg_citation_count": avg_cite,
    }
    metrics: dict[str, Any] = {"heuristic": summary, "per_case": results}

    ragas_report = _try_ragas(results) if args.ragas else None
    if ragas_report:
        metrics["ragas"] = ragas_report
    else:
        metrics["ragas"] = {"skipped": True, "reason": "ragas 未启用或无可用 LLM"}

    print("\n=== 评测汇总 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("faithfulness 目标 ≥ 0.75，answer_relevancy 目标 ≥ 0.8")

    if args.dry_run:
        return 0

    try:
        run_id = await _persist_run(
            run_key=args.run_key,
            golden_file=str(golden_path),
            summary=summary,
            metrics=metrics,
        )
        print(f"[info] 已写入 rag_eval_runs.id={run_id}")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[WARN] 写库失败：{exc}")
        return 1
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 7 RAG evaluation runbook")
    parser.add_argument("--kb-id", required=True, help="目标知识库 ID")
    parser.add_argument("--user-id", required=True, help="评测运行时所扮演的用户 ID")
    parser.add_argument(
        "--golden",
        default=str(Path(__file__).with_name("golden_cases.json")),
        help="金标样例 JSON 文件路径",
    )
    parser.add_argument(
        "--run-key", default="stage7-smoke", help="rag_eval_runs.run_key"
    )
    parser.add_argument(
        "--ragas", action="store_true", help="尝试运行 ragas 指标（可选）"
    )
    parser.add_argument("--dry-run", action="store_true", help="不写库，仅打印指标")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
