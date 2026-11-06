"""Regression tests for serialized disk examinations.

The worker currently has process-global pytsk3 image and filesystem handles.
Concurrent /examine calls must not reset one another's handles. These tests
exercise the scheduling contract without requiring native pytsk3 or disk images.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest

import worker.main as worker_main


def test_examinations_do_not_overlap_or_clobber_image_state(monkeypatch):
    first_entered = Event()
    release_first = Event()
    second_scheduled = Event()
    second_entered = Event()
    active_scans = 0
    maximum_scans = 0
    count_lock = Lock()

    def synthetic_scan(request):
        nonlocal active_scans, maximum_scans
        with count_lock:
            active_scans += 1
            maximum_scans = max(maximum_scans, active_scans)
        try:
            if request.job_id == "first":
                worker_main._img_info = "first image"
                first_entered.set()
                assert release_first.wait(timeout=5), "first scan was not released"
                # A concurrent scan used to reset this process-global handle.
                assert worker_main._img_info == "first image"
            else:
                second_entered.set()
                worker_main._img_info = "second image"
            return worker_main.ExamineResponse(success=True)
        finally:
            with count_lock:
                active_scans -= 1

    monkeypatch.setattr(worker_main, "_examine_sync_unlocked", synthetic_scan)
    original_image = worker_main._img_info

    def run_second():
        second_scheduled.set()
        return worker_main._examine_sync(worker_main.ExamineRequest(
            case_id=2, evidence_id=2, image_path="synthetic-2.img",
            operation="files", job_id="second",
        ))

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(worker_main._examine_sync, worker_main.ExamineRequest(
                case_id=1, evidence_id=1, image_path="synthetic-1.img",
                operation="files", job_id="first",
            ))
            assert first_entered.wait(timeout=5), "first scan did not start"
            second = pool.submit(run_second)
            try:
                assert second_scheduled.wait(timeout=5), "second call was not scheduled"
                assert not second_entered.wait(timeout=0.1), (
                    "second examination entered before first released the image"
                )
            finally:
                release_first.set()
            assert first.result(timeout=5).success
            assert second.result(timeout=5).success
        assert second_entered.is_set()
        assert maximum_scans == 1
    finally:
        release_first.set()
        worker_main._img_info = original_image


def test_failed_examination_releases_lock(monkeypatch):
    def failed_scan(_request):
        raise RuntimeError("synthetic failure")

    request = worker_main.ExamineRequest(
        case_id=1, evidence_id=1, image_path="synthetic.img", operation="files",
    )
    monkeypatch.setattr(worker_main, "_examine_sync_unlocked", failed_scan)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        worker_main._examine_sync(request)

    monkeypatch.setattr(
        worker_main, "_examine_sync_unlocked",
        lambda _request: worker_main.ExamineResponse(success=True),
    )
    assert worker_main._examine_sync(request).success
