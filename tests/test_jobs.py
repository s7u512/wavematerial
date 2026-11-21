# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The job engine end to end: real scheduler and worker subprocesses, fake engine."""

import json
import time

import pytest

from wavematerial.config import Paths, Settings
from wavematerial.engine.fake import ENV
from wavematerial.jobs.lock import AlreadyRunning, InstanceLock
from wavematerial.jobs.scheduler import Scheduler
from wavematerial.jobs.store import JobStore
from wavematerial.preflight import Device

CPU = Device("cpu", "cpu", "Test CPU", None)
IGPU = Device("vulkan", "igpu", "Test GPU", "0000:05:00.0", 8 << 30)


@pytest.fixture
def env(tmp_path, monkeypatch):
    def setup(**fake_options):
        monkeypatch.setenv(ENV, json.dumps(fake_options))
        paths = Paths.under(tmp_path / "app")
        store = JobStore(paths.jobs_db)
        sched = Scheduler(store, paths, Settings, [CPU, IGPU], cores=4)
        source = tmp_path / "apollo11.wav"
        source.write_bytes(b"RIFF" + bytes(4096))
        return sched, store, source

    schedulers = []

    def make(**fake_options):
        sched, store, source = setup(**fake_options)
        schedulers.append(sched)
        return sched, store, source

    yield make
    for s in schedulers:
        s.shutdown()


def wait_for(store, job_id, state, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = store.get(job_id)
        if job.state == state:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} is {store.get(job_id).state}, expected {state}")


def stages_run(sched, job_id):
    return (sched.job_dir(job_id) / "fake-stages.log").read_text(encoding="utf-8").split()


def test_a_job_runs_to_done_in_a_worker(env):
    sched, store, source = env()
    job = sched.add(source, min_speakers=2, max_speakers=3)
    sched.start()
    done = wait_for(store, job.id, "done")
    assert done.progress == 1.0 and "Test GPU" in done.device
    assert (sched.job_dir(job.id) / "outputs" / "transcript.txt").exists()


def test_crashed_job_resumes_from_its_last_saved_stage(env):
    sched, store, source = env()
    job = store.add(source, min_speakers=2, max_speakers=3)
    store.set_state(job.id, "running")  # the app died while this job ran...
    job_dir = sched.job_dir(job.id)
    job_dir.mkdir(parents=True)
    for saved in ("chunks.json", "timings.json"):  # ...after these stages were saved
        (job_dir / saved).write_text("[]\n", encoding="utf-8")

    sched.start()
    wait_for(store, job.id, "done")
    assert stages_run(sched, job.id) == ["decode", "text", "diarize", "merge", "render"]


def test_gpu_failure_reruns_on_the_cpu_and_is_remembered(env):
    sched, store, source = env(gpu_fails_at="text")
    job = sched.add(source, min_speakers=2, max_speakers=3)
    sched.start()
    done = wait_for(store, job.id, "done")
    assert "Test CPU" in done.device
    assert store.unreliable_gpus() == {IGPU.device_id}
    # the CPU rerun resumed after the stages the GPU run had saved
    assert stages_run(sched, job.id) == [
        "decode",
        "vad",
        "timings",
        "decode",
        "text",
        "diarize",
        "merge",
        "render",
    ]


def test_stop_cancels_and_resume_continues(env):
    sched, store, source = env(sleep=0.4)
    job = sched.add(source, min_speakers=2, max_speakers=3)
    sched.start()
    deadline = time.monotonic() + 30
    while store.get(job.id).stage not in ("timings", "text") and time.monotonic() < deadline:
        time.sleep(0.05)
    sched.stop(job.id)
    wait_for(store, job.id, "cancelled")

    sched.resume(job.id)
    wait_for(store, job.id, "done")
    assert stages_run(sched, job.id).count("vad") == 1  # not redone after the stop


def test_a_changed_source_fails_with_a_clear_message(env):
    sched, store, source = env()
    job = sched.add(source, min_speakers=2, max_speakers=3)
    source.write_bytes(b"something else entirely")
    sched.start()
    failed = wait_for(store, job.id, "failed")
    assert "has changed" in failed.error


def test_only_one_instance_holds_the_lock(tmp_path):
    with InstanceLock(tmp_path / "instance.lock"):
        with pytest.raises(AlreadyRunning):
            InstanceLock(tmp_path / "instance.lock").acquire()
    InstanceLock(tmp_path / "instance.lock").acquire()  # free again once released
