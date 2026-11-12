"""Synthetic async load & performance benchmark for AEGIS API endpoints.

Uses existing repository dependencies (``httpx``, ``asyncio``, ``time``, ``statistics``)
to measure p50/p95/p99 latency, throughput (RPS), HTTP status code distribution,
and error rate across core endpoints at configurable concurrency levels.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx


@dataclass(slots=True)
class RequestSample:
    """Single HTTP request measurement."""

    latency_ms: float
    status_code: int
    error: bool


@dataclass(slots=True)
class EndpointBenchmarkResult:
    """Aggregated benchmark metrics for one endpoint at a given concurrency."""

    endpoint_label: str
    concurrency: int
    total_requests: int
    wall_time_s: float
    rps: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    status_counts: dict[int, int]
    error_count: int
    error_rate_pct: float


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Compute linear-interpolated percentile from a sorted list of floats."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


async def _setup_test_context(client: httpx.AsyncClient) -> dict[str, Any]:
    """Register a synthetic tenant and seed guardian + disputeos fixtures."""
    run_id = uuid4().hex[:8]
    reg_resp = await client.post(
        "/v1/auth/register",
        json={
            "email": f"loadtest-{run_id}@example.com",
            "password": "LoadTestPassword!123",
            "full_name": "Load Test Operator",
            "organization_name": f"LoadTest Org {run_id}",
            "organization_slug": f"loadtest-org-{run_id}",
        },
    )
    reg_resp.raise_for_status()
    token = reg_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    agent_resp = await client.post(
        "/v1/guardian/agents",
        headers=headers,
        json={
            "name": f"LoadAgent-{run_id}",
            "purpose": "Synthetic load benchmark",
            "public_fingerprint": f"fp-load-{run_id}",
        },
    )
    agent_resp.raise_for_status()
    agent_id = agent_resp.json()["id"]

    merchant_resp = await client.post(
        "/v1/guardian/merchants",
        headers=headers,
        json={
            "name": "LoadBench Cloud",
            "domain": f"loadbench-{run_id}.example.com",
            "category": "SOFTWARE",
            "is_allowlisted": True,
        },
    )
    merchant_resp.raise_for_status()
    merchant_id = merchant_resp.json()["id"]

    passport_resp = await client.post(
        "/v1/guardian/passports",
        headers=headers,
        json={
            "agent_id": agent_id,
            "total_budget_minor": 1_000_000_000,
            "per_tx_limit_minor": 5000,
            "daily_limit_minor": 500_000_000,
            "human_approval_threshold_minor": 3000,
            "allowed_merchant_ids": [merchant_id],
            "allowed_categories": ["SOFTWARE"],
        },
    )
    passport_resp.raise_for_status()
    passport_id = passport_resp.json()["id"]

    seed_prop_resp = await client.post(
        "/v1/guardian/proposals",
        headers=headers,
        json={
            "agent_id": agent_id,
            "passport_id": passport_id,
            "merchant_id": merchant_id,
            "merchant_name": "LoadBench Cloud",
            "merchant_category": "SOFTWARE",
            "amount_minor": 1500,
            "currency": "USD",
            "item_summary": "Seed Load Payment",
            "rationale": "Seed payment for GET and replay load tests",
            "idempotency_key": f"seed-load-{run_id}",
        },
    )
    seed_prop_resp.raise_for_status()
    seed_intent_id = seed_prop_resp.json()["payment_intent"]["id"]

    seed_case_resp = await client.post("/v1/disputeos/cases/seed-demo", headers=headers)
    seed_case_resp.raise_for_status()

    return {
        "headers": headers,
        "agent_id": agent_id,
        "merchant_id": merchant_id,
        "passport_id": passport_id,
        "payment_intent_id": seed_intent_id,
    }


async def _benchmark_endpoint(
    client: httpx.AsyncClient,
    *,
    label: str,
    request_fn: Callable[[int], Any],
    concurrency: int,
    total_requests: int,
) -> EndpointBenchmarkResult:
    """Execute ``total_requests`` against one endpoint with bounded concurrency."""
    sem = asyncio.Semaphore(concurrency)
    samples: list[RequestSample] = []

    async def _worker(idx: int) -> None:
        async with sem:
            t0 = time.perf_counter()
            try:
                resp: httpx.Response = await request_fn(idx)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                is_err = resp.status_code >= 400
                samples.append(
                    RequestSample(
                        latency_ms=elapsed_ms,
                        status_code=resp.status_code,
                        error=is_err,
                    )
                )
            except httpx.HTTPError:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                samples.append(RequestSample(latency_ms=elapsed_ms, status_code=0, error=True))

    wall_start = time.perf_counter()
    await asyncio.gather(*(_worker(i) for i in range(total_requests)))
    wall_time_s = max(time.perf_counter() - wall_start, 1e-9)

    latencies = sorted(s.latency_ms for s in samples)
    status_counter = Counter(s.status_code for s in samples)
    error_count = sum(1 for s in samples if s.error)

    return EndpointBenchmarkResult(
        endpoint_label=label,
        concurrency=concurrency,
        total_requests=total_requests,
        wall_time_s=wall_time_s,
        rps=total_requests / wall_time_s,
        p50_ms=statistics.median(latencies) if latencies else 0.0,
        p95_ms=_percentile(latencies, 95.0),
        p99_ms=_percentile(latencies, 99.0),
        min_ms=latencies[0] if latencies else 0.0,
        max_ms=latencies[-1] if latencies else 0.0,
        status_counts=dict(sorted(status_counter.items())),
        error_count=error_count,
        error_rate_pct=(error_count / total_requests) * 100.0 if total_requests else 0.0,
    )


def _print_results_table(results: list[EndpointBenchmarkResult]) -> None:
    """Print benchmark results as a formatted markdown/console table."""
    header = (
        f"{'Endpoint':<42} | {'Conc':>4} | {'Reqs':>4} | "
        f"{'p50(ms)':>8} | {'p95(ms)':>8} | {'p99(ms)':>8} | "
        f"{'RPS':>8} | {'Err%':>6} | Statuses"
    )
    print("\n" + header)
    print("-" * len(header))
    for r in results:
        statuses = ", ".join(f"{k}:{v}" for k, v in r.status_counts.items())
        print(
            f"{r.endpoint_label:<42} | {r.concurrency:>4} | {r.total_requests:>4} | "
            f"{r.p50_ms:>8.2f} | {r.p95_ms:>8.2f} | {r.p99_ms:>8.2f} | "
            f"{r.rps:>8.2f} | {r.error_rate_pct:>5.1f}% | {statuses}"
        )


async def run_benchmarks(
    *,
    base_url: str,
    concurrency_levels: list[int],
    requests_per_endpoint: int,
    timeout_s: float,
) -> list[EndpointBenchmarkResult]:
    """Run all configured endpoint benchmarks across the requested concurrency levels."""
    limits = httpx.Limits(
        max_connections=max(concurrency_levels) * 2,
        max_keepalive_connections=max(concurrency_levels),
    )
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout_s, limits=limits) as client:
        ctx = await _setup_test_context(client)
        headers = ctx["headers"]
        payment_id = ctx["payment_intent_id"]

        endpoints: list[tuple[str, Callable[[int], Any]]] = [
            ("GET /health", lambda _i: client.get("/health")),
            (
                "POST /v1/guardian/proposals",
                lambda i: client.post(
                    "/v1/guardian/proposals",
                    headers=headers,
                    json={
                        "agent_id": ctx["agent_id"],
                        "passport_id": ctx["passport_id"],
                        "merchant_id": ctx["merchant_id"],
                        "merchant_name": "LoadBench Cloud",
                        "merchant_category": "SOFTWARE",
                        "amount_minor": 1500,
                        "currency": "USD",
                        "item_summary": f"Load Item {i}",
                        "rationale": "Synthetic load test proposal",
                        "idempotency_key": f"load-{uuid4().hex}",
                    },
                ),
            ),
            (
                "GET /v1/guardian/payments/{id}",
                lambda _i: client.get(f"/v1/guardian/payments/{payment_id}", headers=headers),
            ),
            (
                "POST /v1/ghostpay/replay/by-payment/{id}",
                lambda _i: client.post(
                    f"/v1/ghostpay/replay/by-payment/{payment_id}",
                    headers=headers,
                    json={"persist_investigation": False},
                ),
            ),
            (
                "GET /v1/disputeos/cases",
                lambda _i: client.get("/v1/disputeos/cases", headers=headers),
            ),
        ]

        all_results: list[EndpointBenchmarkResult] = []
        for conc in concurrency_levels:
            for label, req_fn in endpoints:
                res = await _benchmark_endpoint(
                    client,
                    label=label,
                    request_fn=req_fn,
                    concurrency=conc,
                    total_requests=requests_per_endpoint,
                )
                all_results.append(res)

        _print_results_table(all_results)
        return all_results


def main() -> int:
    """CLI entry point for synthetic load benchmark."""
    parser = argparse.ArgumentParser(description="AEGIS API synthetic load benchmark")
    parser.add_argument("--base-url", default="http://127.0.0.1:18011", help="Target API base URL")
    parser.add_argument(
        "--concurrency",
        type=int,
        nargs="+",
        default=[10, 25],
        help="Concurrency levels to benchmark",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=50,
        help="Total requests per endpoint per concurrency level",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP request timeout in seconds")
    args = parser.parse_args()

    results = asyncio.run(
        run_benchmarks(
            base_url=args.base_url,
            concurrency_levels=args.concurrency,
            requests_per_endpoint=args.requests,
            timeout_s=args.timeout,
        )
    )
    total_errors = sum(r.error_count for r in results)
    return 1 if total_errors > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
