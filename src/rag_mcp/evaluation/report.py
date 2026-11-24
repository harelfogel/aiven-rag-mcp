"""The markdown report: the summary table for the README, the misses, and every rank."""

from __future__ import annotations

from collections.abc import Sequence

from rag_mcp.evaluation.runner import RECALL_AT, Report


def render_markdown(reports: Sequence[Report], *, chunk_count: int, repeats: int) -> str:
    """The table that goes into the README, plus the misses of the last variant for honesty."""
    lines = [
        f"{len(reports[0].outcomes)} golden questions over {chunk_count} chunks, "
        f"latency over {repeats} run(s) per question, model inference included.",
        "",
        "| Variant | Recall@1 | Recall@5 | MRR | p50 ms | p95 ms |",
        "|---|---|---|---|---|---|",
    ]
    for r in reports:
        lines.append(
            f"| {r.variant.label} | {r.recall_at_1:.2f} | {r.recall_at_5:.2f} | {r.mrr:.2f} "
            f"| {r.p50_ms:.0f} | {r.p95_ms:.0f} |"
        )
    best = max(reports, key=lambda r: (r.recall_at_5, r.mrr))
    lines += ["", f"Recall@5 by question kind, {best.variant.label}:", ""]
    lines += ["| Kind | Recall@5 |", "|---|---|"]
    lines += [f"| {kind} | {value:.2f} |" for kind, value in best.recall_at_5_by_kind().items()]
    misses = [o for o in best.outcomes if o.rank is None or o.rank > RECALL_AT]
    lines += ["", f"Not in the top {RECALL_AT} for {best.variant.label}:", ""]
    lines += [f"- {o.question.id}: rank {o.rank if o.rank else 'none'}" for o in misses] or [
        "- none"
    ]
    lines += ["", "Rank of the expected page per question (none = not in the top 20):", ""]
    lines += ["| Question | " + " | ".join(r.variant.label for r in reports) + " |"]
    lines += ["|---|" + "---|" * len(reports)]
    for index, outcome in enumerate(reports[0].outcomes):
        ranks = [r.outcomes[index].rank for r in reports]
        cells = " | ".join(str(rank) if rank else "none" for rank in ranks)
        lines.append(f"| {outcome.question.id} | {cells} |")
    return "\n".join(lines) + "\n"
