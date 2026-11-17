"""B4 baselines and workflow ablations.

rules_only / workflow_no_draft: same decisions as workflow, zero model calls.
workflow_no_investigator: do not read the order; escalate instead of quoting.
workflow_no_check: do not run compute_compensation; fail closed with no refund.
swarm_pruned: reference swarm, but peer/parse model calls are dropped from the seed.
"""

from __future__ import annotations

import random
import sqlite3

from lab8.db import connect
from lab8.durability import InjectedCrash, issue_refund
from lab8.handoff import make_handoff
from lab8.mock_llm import complete, parse_delay_days
from lab8.runtime import run_readonly_investigators
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish, safe_dump
from lab8.tools import compute_compensation, get_claim_view, lookup_order, tool_cost
from lab8.trace import Trace


def prune_decision(seed: int) -> dict[str, bool]:
    """Whether to drop the peer and parse model calls. True means drop.

    The draw depends only on the seed, so every claim in that seed is pruned
    the same way and a rerun matches.
    """
    rng = random.Random(seed)
    return {"peer": rng.random() < 0.5, "parse": rng.random() < 0.5}


def run_rules_only(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    return _run_workflow(
        claim_id,
        seed=seed,
        store_path=store_path,
        crash_at=crash_at,
        shape="rules_only",
        draft=False,
        investigator=True,
        check=True,
    )


def run_no_draft(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    return _run_workflow(
        claim_id,
        seed=seed,
        store_path=store_path,
        crash_at=crash_at,
        shape="workflow_no_draft",
        draft=False,
        investigator=True,
        check=True,
    )


def run_no_investigator(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    return _run_workflow(
        claim_id,
        seed=seed,
        store_path=store_path,
        crash_at=crash_at,
        shape="workflow_no_investigator",
        draft=True,
        investigator=False,
        check=True,
    )


def run_no_check(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    return _run_workflow(
        claim_id,
        seed=seed,
        store_path=store_path,
        crash_at=crash_at,
        shape="workflow_no_check",
        draft=True,
        investigator=True,
        check=False,
    )


def _run_workflow(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None,
    shape: str,
    draft: bool,
    investigator: bool,
    check: bool,
) -> RunResult:
    conn = connect(store_path)
    try:
        return _workflow(
            conn,
            claim_id,
            seed=seed,
            crash_at=crash_at,
            shape=shape,
            draft=draft,
            investigator=investigator,
            check=check,
        )
    finally:
        conn.close()


def _workflow(
    conn: sqlite3.Connection,
    claim_id: str,
    *,
    seed: int,
    crash_at: str | None,
    shape: str,
    draft: bool,
    investigator: bool,
    check: bool,
) -> RunResult:
    budget = Budget()
    trace = Trace(make_run_id(shape, claim_id, seed))

    def done(status: str, amount: int, reason: str | None = None) -> RunResult:
        trace.add("decision", {"status": status, "proposal_amount": amount, "reason": reason})
        return finish(
            conn,
            shape=shape,
            claim_id=claim_id,
            seed=seed,
            status=status,
            proposal_amount=amount,
            budget=budget,
            trace=trace,
            error_reason=reason,
        )

    budget.add_tool(tool_cost())
    claim = get_claim_view(conn, claim_id)
    if not claim["found"]:
        return done("failed", 0, "unknown_claim")
    trace.add("claim", {"claim_id": claim_id, "has_order_id": bool(claim["order_id"])})

    if not claim["order_id"]:
        return done("needs_info", 0, "missing_order_id")

    if not investigator:
        return done("escalated", 0, "investigator_removed")

    budget.add_tool(tool_cost())
    view = lookup_order(conn, claim["order_id"], claim["principal_id"])
    if not view["visible"]:
        return done("escalated", 0, view.get("reason"))
    trace.add("order", view["order"])

    if not check:
        return done("denied", 0, "check_removed")

    budget.add_tool(tool_cost())
    quote = compute_compensation(conn, view["order"])
    trace.add("quote", quote)
    proposal = int(quote["amount_vnd"])
    if proposal <= 0:
        return done("denied", 0, quote.get("reason"))

    try:
        outcome = issue_refund(conn, claim_id, proposal, crash_at=crash_at)
    except InjectedCrash:
        trace.add("crash", {"at": crash_at})
        trace.write()
        raise
    trace.add("host", {"ok": outcome["ok"], "reason": outcome["reason"]})

    if draft:
        complete(budget, seed=seed, purpose="draft", prompt=f"outcome={outcome['reason']}")

    if not outcome["ok"]:
        return done("failed" if outcome["conflict"] else "denied", proposal, outcome["reason"])
    return done("resolved", proposal)


def run_swarm_pruned(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    conn = connect(store_path)
    try:
        return _swarm_pruned(conn, claim_id, seed=seed, crash_at=crash_at)
    finally:
        conn.close()


def _call_model(budget: Budget, *, seed: int, purpose: str, prompt: str, drop: dict[str, bool]) -> str:
    if drop.get(purpose):
        return ""
    return complete(budget, seed=seed, purpose=purpose, prompt=prompt)


def _swarm_pruned(
    conn: sqlite3.Connection,
    claim_id: str,
    *,
    seed: int,
    crash_at: str | None,
) -> RunResult:
    """Reference swarm with peer/parse model calls removed according to the seed.

    parse_delay_days still runs. Dropping the model call does not remove the
    seed-%-5 ticket override, so the decision stays the reference decision.
    """
    shape = "swarm_pruned"
    budget = Budget()
    run_id = make_run_id(shape, claim_id, seed)
    trace = Trace(run_id)
    drop = prune_decision(seed)
    budget.add_tool(tool_cost())
    claim_row = conn.execute(
        "SELECT claim_id, principal_id, order_id, ticket FROM claims WHERE claim_id = ?",
        (claim_id,),
    ).fetchone()
    if claim_row is None:
        trace.add("error", {"reason": "unknown_claim"})
        return finish(
            conn,
            shape=shape,
            claim_id=claim_id,
            seed=seed,
            status="failed",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason="unknown_claim",
        )

    ticket = claim_row["ticket"]
    _call_model(budget, seed=seed, purpose="peer", prompt=ticket, drop=drop)
    parsed_delay = parse_delay_days(ticket)
    _call_model(budget, seed=seed, purpose="parse", prompt=ticket, drop=drop)

    if not claim_row["order_id"]:
        _call_model(budget, seed=seed, purpose="draft", prompt="needs_info", drop=drop)
        trace.add("decision", {"status": "needs_info"})
        return finish(
            conn,
            shape=shape,
            claim_id=claim_id,
            seed=seed,
            status="needs_info",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason="missing_order_id",
        )

    handoff = make_handoff(
        request_id=f"REQ-{claim_id}",
        claim_id=claim_id,
        task="check_applicable_policy",
        facts={},
        allowed_tools=["lookup_order", "lookup_policy", "compute_compensation"],
    )
    trace.add("handoff", safe_dump(handoff))
    investigated = run_readonly_investigators(
        conn, budget, handoff, principal_id=claim_row["principal_id"]
    )
    order_view = investigated["tools"].get("lookup_order", {})
    trace.add(
        "investigator",
        {
            "lookup_order": order_view,
            "policy_count": len((investigated["tools"].get("lookup_policy") or {}).get("policies") or []),
        },
    )
    if not order_view.get("visible"):
        _call_model(budget, seed=seed, purpose="draft", prompt="escalated", drop=drop)
        return finish(
            conn,
            shape=shape,
            claim_id=claim_id,
            seed=seed,
            status="escalated",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason=order_view.get("reason"),
        )

    order = dict(order_view["order"])
    if parsed_delay is not None and parsed_delay != int(order["delay_days"]) and seed % 5 == 0:
        order["delay_days"] = parsed_delay
        trace.add("model_override", {"delay_days": parsed_delay})

    quote_payload = investigated["tools"]["compute_compensation"]
    if order["delay_days"] != order_view["order"]["delay_days"]:
        budget.add_tool(tool_cost())
        quote_payload = compute_compensation(conn, order)
    proposal = int(quote_payload["amount_vnd"])
    trace.add("quote", quote_payload)
    _call_model(budget, seed=seed, purpose="draft", prompt=f"proposal={proposal}", drop=drop)

    if proposal <= 0:
        return finish(
            conn,
            shape=shape,
            claim_id=claim_id,
            seed=seed,
            status="denied",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason=quote_payload.get("reason"),
        )

    try:
        outcome = issue_refund(conn, claim_id, proposal, crash_at=crash_at)
    except InjectedCrash:
        trace.add("crash", {"at": crash_at})
        trace.write()
        raise

    if not outcome["ok"]:
        status = "failed" if outcome["conflict"] else "denied"
        return finish(
            conn,
            shape=shape,
            claim_id=claim_id,
            seed=seed,
            status=status,
            proposal_amount=proposal,
            budget=budget,
            trace=trace,
            error_reason=outcome["reason"],
        )
    return finish(
        conn,
        shape=shape,
        claim_id=claim_id,
        seed=seed,
        status="resolved",
        proposal_amount=proposal,
        budget=budget,
        trace=trace,
        error_reason=None,
    )
