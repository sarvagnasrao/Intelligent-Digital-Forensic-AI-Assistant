"""The processing coordinator must never start work implicitly."""

import pytest

from app.processing.service import STAGES, ProcessingService, Stage


def plan(service, stages=STAGES, **kwargs):
    return service.create_plan(
        actor_id=7, scope={"case_id": 1}, settings={}, selected_stages=stages, **kwargs
    )


def test_explicit_approval_serial_execution_and_progress():
    seen = []
    service = ProcessingService({stage: lambda ctx: seen.append(ctx.stage) for stage in STAGES})
    pending = plan(service, reversed(STAGES))
    assert seen == []
    with pytest.raises(ValueError, match="approval"):
        service.run(pending.run_id)
    service.approve(pending.run_id, approved_by=9)
    assert seen == []
    result = service.run(pending.run_id)
    assert seen == list(STAGES)
    assert result.status == "completed"
    assert result.progress == 1
    assert result.actor_id == 7
    assert result.approved_by == 9
    assert result.approved_at is not None
    assert "In-memory" in result.persistence_limitation
    with pytest.raises(ValueError, match="only once"):
        service.run(pending.run_id)


def test_missing_prerequisites_block_without_calls():
    service = ProcessingService({Stage.ANALYZE: lambda ctx: pytest.fail("must not execute")})
    pending = plan(service, [Stage.ANALYZE])
    service.approve(pending.run_id, approved_by=7)
    result = service.run(pending.run_id)
    assert result.status == "blocked"
    assert result.stages[0].blocked_by == (Stage.VERIFY, Stage.EXTRACT, Stage.INDEX)


def test_selected_stage_uses_explicit_completed_prerequisites():
    seen = []
    service = ProcessingService({Stage.INDEX: lambda ctx: seen.append(ctx.stage)})
    pending = plan(service, [Stage.INDEX], completed_prerequisites=[Stage.VERIFY, Stage.EXTRACT])
    service.approve(pending.run_id, approved_by=7)
    assert service.run(pending.run_id).status == "completed"
    assert seen == [Stage.INDEX]


def test_failure_blocks_remaining_stages_and_retains_error():
    def fail(ctx):
        raise RuntimeError("extract failed")

    service = ProcessingService({Stage.VERIFY: lambda ctx: None, Stage.EXTRACT: fail})
    pending = plan(service)
    service.approve(pending.run_id, approved_by=7)
    result = service.run(pending.run_id)
    assert result.status == "failed"
    assert result.stages[1].error == "RuntimeError: extract failed"
    assert result.stages[2].blocked_by == (Stage.EXTRACT,)
    assert result.progress == 0.2


def test_cancel_during_callback_finishes_current_stage_only():
    def cancel(ctx):
        assert service.get(ctx.run_id).stages[0].status == "running"
        service.cancel(ctx.run_id)

    service = ProcessingService({Stage.VERIFY: cancel})
    pending = plan(service)
    service.approve(pending.run_id, approved_by=7)
    result = service.run(pending.run_id)
    assert result.status == "cancelled"
    assert result.stages[0].status == "completed"
    assert all(item.status == "cancelled" for item in result.stages[1:])


def test_cancel_before_approval_prevents_execution():
    service = ProcessingService({})
    pending = plan(service)
    assert service.cancel(pending.run_id).status == "cancelled"
    with pytest.raises(ValueError, match="pending plan"):
        service.approve(pending.run_id, approved_by=7)


def test_scope_settings_are_immutable_snapshots():
    scope = {"evidence_ids": [1]}
    settings = {"analysis": {"model": "manual"}}
    service = ProcessingService({})
    pending = service.create_plan(
        actor_id=1, scope=scope, settings=settings, selected_stages=[Stage.VERIFY]
    )
    scope["evidence_ids"].append(2)
    settings["analysis"]["model"] = "changed"
    assert pending.scope["evidence_ids"] == (1,)
    assert pending.settings["analysis"]["model"] == "manual"
    with pytest.raises(TypeError):
        pending.settings["analysis"]["model"] = "mutated"


def test_unconfigured_callback_fails_explicitly():
    service = ProcessingService({})
    pending = plan(service, [Stage.VERIFY])
    service.approve(pending.run_id, approved_by=7)
    result = service.run(pending.run_id)
    assert result.status == "failed"
    assert "No callback configured" in result.stages[0].error


def test_invalid_plans_rejected():
    service = ProcessingService({})
    with pytest.raises(ValueError, match="at least one"):
        plan(service, [])
    with pytest.raises(ValueError, match="also be completed"):
        plan(service, [Stage.VERIFY], completed_prerequisites=[Stage.VERIFY])
    with pytest.raises(ValueError, match="actor ID"):
        service.create_plan(actor_id="", scope={}, settings={}, selected_stages=STAGES)
