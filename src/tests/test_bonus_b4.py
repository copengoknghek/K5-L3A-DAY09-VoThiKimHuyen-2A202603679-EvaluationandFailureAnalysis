"""Bonus B4: rules-only, pruned swarm, workflow ablations, paired stats."""

from __future__ import annotations

from lab8.db import connect, init_store
from lab8.shapes import SHAPES
from tests.conftest import CLAIMS, WORLD

from bonus.stats import bootstrap_pass_rate_ci, mcnemar_exact, sign_test
from bonus.variants import (
    prune_decision,
    run_no_check,
    run_no_draft,
    run_no_investigator,
    run_rules_only,
    run_swarm_pruned,
)


def _store(tmp_path, name: str):
    path = tmp_path / name
    init_store(path, WORLD, CLAIMS).close()
    return path


def _refund_count(store, claim_id: str) -> int:
    conn = connect(store)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM refund_ledger WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
        return int(row["n"])
    finally:
        conn.close()


def test_rules_only_matches_workflow_and_calls_no_model(tmp_path):
    for claim_id in ("C-001", "C-002", "C-004", "C-005"):
        for seed in (11, 55):
            base = _store(tmp_path, f"wf-{claim_id}-{seed}.sqlite")
            alt = _store(tmp_path, f"ro-{claim_id}-{seed}.sqlite")
            workflow = SHAPES["workflow"](claim_id, seed=seed, store_path=str(base))
            rules = run_rules_only(claim_id, seed=seed, store_path=str(alt))
            assert rules.status == workflow.status
            assert rules.proposal_amount == workflow.proposal_amount
            assert rules.model_calls == 0
            assert rules.refund_effects == workflow.refund_effects


def test_no_draft_collapses_to_rules_only(tmp_path):
    base = _store(tmp_path, "draft-a.sqlite")
    alt = _store(tmp_path, "draft-b.sqlite")
    rules = run_rules_only("C-001", seed=22, store_path=str(base))
    draft = run_no_draft("C-001", seed=22, store_path=str(alt))
    assert draft.model_calls == 0
    assert draft.status == rules.status == "resolved"
    assert draft.proposal_amount == rules.proposal_amount
    assert _refund_count(alt, "C-001") == 1


def test_removing_investigator_or_check_does_not_refund(tmp_path):
    missing = _store(tmp_path, "inv-missing.sqlite")
    info = run_no_investigator("C-004", seed=11, store_path=str(missing))
    assert info.status == "needs_info"
    assert info.refund_effects == []

    order = _store(tmp_path, "inv-order.sqlite")
    blocked = run_no_investigator("C-001", seed=11, store_path=str(order))
    assert blocked.status == "escalated"
    assert blocked.proposal_amount == 0
    assert _refund_count(order, "C-001") == 0

    unchecked = _store(tmp_path, "check.sqlite")
    denied = run_no_check("C-001", seed=11, store_path=str(unchecked))
    assert denied.status == "denied"
    assert denied.proposal_amount == 0
    assert _refund_count(unchecked, "C-001") == 0

    still_denied = _store(tmp_path, "check-t02.sqlite")
    t02 = run_no_check("C-002", seed=55, store_path=str(still_denied))
    assert t02.status == "denied"
    assert t02.proposal_amount == 0


def test_swarm_pruned_keeps_decision_and_drops_peer_or_parse(tmp_path):
    dropped = [seed for seed in (11, 22, 33, 44, 55) if any(prune_decision(seed).values())]
    assert dropped, "at least one public seed must drop a peer or parse call"
    for claim_id, seed in (("C-001", 11), ("C-002", 55), ("C-004", 33)):
        base = _store(tmp_path, f"sw-{claim_id}-{seed}.sqlite")
        alt = _store(tmp_path, f"sp-{claim_id}-{seed}.sqlite")
        again = _store(tmp_path, f"sp2-{claim_id}-{seed}.sqlite")
        swarm = SHAPES["swarm"](claim_id, seed=seed, store_path=str(base))
        pruned = run_swarm_pruned(claim_id, seed=seed, store_path=str(alt))
        repeat = run_swarm_pruned(claim_id, seed=seed, store_path=str(again))
        assert pruned.status == swarm.status
        assert pruned.proposal_amount == swarm.proposal_amount
        assert pruned.model_calls <= swarm.model_calls
        assert repeat.status == pruned.status
        assert repeat.proposal_amount == pruned.proposal_amount
        assert repeat.model_calls == pruned.model_calls
        if any(prune_decision(seed).values()):
            assert pruned.model_calls < swarm.model_calls


def test_bootstrap_ci_and_exact_mcnemar():
    trials = []
    for claim_id in ("C-1", "C-2"):
        for seed in (11, 22):
            trials.append({"claim_id": claim_id, "seed": seed, "passed": True, "cost_estimate": 1.0})
    ci = bootstrap_pass_rate_ci(trials, resamples=200, seed=1)
    assert ci["point"] == 1.0
    assert ci["low"] == 1.0
    assert ci["high"] == 1.0

    same = mcnemar_exact(trials, trials)
    assert same["discordant"] == 0
    assert same["p_value"] == 1.0

    left = [{"claim_id": f"C-{i}", "seed": 11, "passed": True} for i in range(8)]
    right = [{"claim_id": f"C-{i}", "seed": 11, "passed": False} for i in range(8)]
    gap = mcnemar_exact(left, right)
    assert gap["b"] == 0
    assert gap["c"] == 8
    assert abs(gap["p_value"] - (2 / 256)) < 1e-12

    one = mcnemar_exact(
        [{"claim_id": "C-002", "seed": 55, "passed": True}],
        [{"claim_id": "C-002", "seed": 55, "passed": False}],
    )
    assert one["discordant"] == 1
    assert one["p_value"] == 1.0

    costs_a = [
        {"claim_id": "C-1", "seed": 11, "cost_estimate": 1.0},
        {"claim_id": "C-1", "seed": 22, "cost_estimate": 1.0},
    ]
    costs_b = [
        {"claim_id": "C-1", "seed": 11, "cost_estimate": 3.0},
        {"claim_id": "C-1", "seed": 22, "cost_estimate": 3.0},
    ]
    signed = sign_test(costs_a, costs_b, value="cost_estimate")
    assert signed["n"] == 2
    assert signed["negative"] == 2
    assert signed["p_value"] == 0.5
