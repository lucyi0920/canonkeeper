"""End-to-end run of the demo scenario against the live models (in-memory store).

verify → regenerate the appearance finding → editor decision on narrative findings → ship.
Usage: python -m scripts.e2e_demo [--no-regen]
"""
import asyncio
import sys
import time
import uuid

from canonkeeper import pipeline, store


def print_run(run_id: str) -> None:
    for s in store.docs().get("runs", run_id)["steps"]:
        if s["status"] != "running":
            print(f"   [{s['t_ms'] / 1000:5.1f}s] {s['status']:<5} {s['actor']:<26} {s['action']} — {s['detail'][:220]}")


def print_report(r) -> None:
    print(f"   score={r.score} checks={r.checks_passed}/{r.checks_total} failed={r.checks_failed} shippable={r.shippable}")
    for f in r.findings:
        adj = f.adjudication.verdict if f.adjudication else "-"
        print(f"   • {f.id} [{f.status}] {f.severity} {f.dimension} {f.panel_ref} — {f.title} (adjudicator: {adj}, regen={f.can_regenerate})")


async def main() -> None:
    s = pipeline.create_session("demo")
    print("session", s.session_id)
    t = time.time()
    run = uuid.uuid4().hex
    report = await pipeline.verify(s.session_id, run)
    print(f"VERIFY ({time.time() - t:.0f}s)")
    print_run(run)
    print_report(report)

    if "--no-regen" not in sys.argv:
        for f in [f for f in report.findings if f.status == "open" and f.can_regenerate]:
            t = time.time()
            run = uuid.uuid4().hex
            report = await pipeline.regenerate(s.session_id, f.id, run)
            print(f"REGENERATE {f.id} ({time.time() - t:.0f}s)")
            print_run(run)
            print_report(report)

    for f in [f for f in report.findings if f.status == "open" and not f.can_regenerate]:
        report = pipeline.decide(s.session_id, f.id, "dismiss", "Intentional: vision of Mira")
        print(f"DISMISS {f.id}")
        print_report(report)

    try:
        pipeline.ship(s.session_id)
        print("SHIPPED ✅")
    except ValueError as exc:
        print("SHIP BLOCKED:", exc)


if __name__ == "__main__":
    asyncio.run(main())
