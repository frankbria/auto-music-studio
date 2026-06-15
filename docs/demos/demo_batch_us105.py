"""Live demo driver for US-10.5 batch processing endpoints (issue #85).

Drives the real FastAPI app over httpx ASGI against a throwaway MongoDB,
exercising every acceptance criterion and printing outcome evidence. Stems use a
lightweight StemsClient double (no demucs); export uses the real ffmpeg-backed
export_audio so the produced file is genuine.

Usage: ACEMUSIC_TEST_MONGODB_URL=mongodb://localhost:27017 uv run python docs/demos/demo_batch_us105.py
"""

import asyncio
import os
import tempfile
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf

_TMP = tempfile.mkdtemp(prefix="demo-us105-")
os.environ["ACEMUSIC_STORAGE_BACKEND"] = "local"
os.environ["ACEMUSIC_STORAGE_LOCAL_ROOT"] = str(Path(_TMP) / "storage")

import httpx  # noqa: E402
from beanie import PydanticObjectId  # noqa: E402

from acemusic.api import database  # noqa: E402
from acemusic.api.auth.tokens import create_access_token  # noqa: E402
from acemusic.api.main import API_V1_PREFIX, create_app  # noqa: E402
from acemusic.api.models import BatchJob, Clip, Workspace  # noqa: E402
from acemusic.api.services import users as user_service  # noqa: E402
from acemusic.api.settings import ApiSettings  # noqa: E402
from acemusic.api.tasks import extraction as extraction_tasks  # noqa: E402
from acemusic.api.tasks.processor import JobProcessor  # noqa: E402
from acemusic.storage import get_storage_backend  # noqa: E402

BATCH = f"{API_V1_PREFIX}/batch"
STEM_LABELS = ["drums", "bass", "other", "vocals"]


class _FakeStemsClient:
    model_samplerate = 44100

    def separate(self, audio_path, progress_callback=None):
        return {label: label for label in STEM_LABELS}

    def save_stems(self, stems, output_dir, base_name, sample_rate=44100, output_format="wav"):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        tone = (0.2 * np.sin(2 * np.pi * 220 * np.linspace(0, 0.5, int(sample_rate * 0.5), endpoint=False))).astype(
            np.float32
        )
        paths = {}
        for label in STEM_LABELS:
            path = output_dir / f"{base_name}-{label}.{output_format}"
            sf.write(str(path), np.column_stack([tone, tone]), sample_rate)
            paths[label] = path
        return paths


def _headers(user, settings):
    token = create_access_token(
        user_id=str(user.id), email=user.email, subscription_tier=user.subscription_tier, settings=settings
    )
    return {"Authorization": f"Bearer {token}"}


def _tone_bytes(path: Path, *, fmt="wav", seconds=1.0) -> bytes:
    sr = 44100
    tone = (0.2 * np.sin(2 * np.pi * 220 * np.linspace(0, seconds, int(sr * seconds), endpoint=False))).astype(
        np.float32
    )
    wav = path.with_suffix(".wav")
    sf.write(str(wav), np.column_stack([tone, tone]), sr)
    if fmt == "wav":
        return wav.read_bytes()
    from pydub import AudioSegment  # only when transcoding the source

    out = path.with_suffix(f".{fmt}")
    AudioSegment.from_file(str(wav), format="wav").export(str(out), format=fmt)
    return out.read_bytes()


async def _insert_clip(user, ws, *, fmt="wav", with_bytes=False) -> Clip:
    cid = PydanticObjectId()
    file_path = f"{user.id}/{ws.id}/clips/{cid}.{fmt}"
    if with_bytes:
        get_storage_backend().upload(file_path, _tone_bytes(Path(_TMP) / str(cid), fmt=fmt))
    clip = Clip(id=cid, user_id=user.id, workspace_id=ws.id, file_path=file_path, format=fmt, duration=1.0, bpm=120)
    await clip.insert()
    return clip


async def _poll(client, batch_id, headers, *, timeout=30.0):
    proc = JobProcessor(concurrency=2, poll_interval=0.05)
    await proc.start()
    try:
        deadline = asyncio.get_event_loop().time() + timeout
        body = None
        while asyncio.get_event_loop().time() < deadline:
            r = await client.get(f"{BATCH}/{batch_id}/status", headers=headers)
            body = r.json()
            if body["overall_status"] in ("completed", "failed", "partial_success"):
                break
            await asyncio.sleep(0.05)
        return body
    finally:
        await proc.stop()


def _line(title):
    print(f"\n{'=' * 4} {title} {'=' * 4}")


async def main() -> None:
    extraction_tasks.StemsClient = _FakeStemsClient  # avoid demucs

    settings = ApiSettings(
        _env_file=None,
        mongodb_url=os.environ.get("ACEMUSIC_TEST_MONGODB_URL", "mongodb://localhost:27017"),
        mongodb_db_name=f"acemusic_demo_{uuid.uuid4().hex[:8]}",
        jwt_secret_key="demo-secret-key-at-least-32-bytes-long-xx",
        job_processor_enabled=False,
    )
    mongo_client = await database.init_db(settings)
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://demo") as client:
            user = await user_service.get_or_create_user(
                email="demo@example.com", provider="google", oauth_id="g-demo", name="Demo"
            )
            ws = Workspace(name="Demo WS", user_id=user.id)
            await ws.insert()
            headers = _headers(user, settings)

            # --- AC3: >50 clips -> 422 -----------------------------------
            _line("AC3  POST /batch/stems with 51 clips -> 422")
            ids51 = [str(PydanticObjectId()) for _ in range(51)]
            r = await client.post(f"{BATCH}/stems", json={"clip_ids": ids51}, headers=headers)
            print(f"51 clips  -> HTTP {r.status_code}  (detail: {r.json()['detail'][0]['type']})")
            ids50 = [str(PydanticObjectId()) for _ in range(50)]
            r50 = await client.post(f"{BATCH}/stems", json={"clip_ids": ids50}, headers=headers)
            print(f"50 clips  -> HTTP {r50.status_code}  (boundary accepted)")

            # --- AC1 + AC4: batch stems, individual status, partial success
            _line("AC1+AC4  POST /batch/stems: 2 good clips + 1 unknown id")
            good = [await _insert_clip(user, ws, with_bytes=True) for _ in range(2)]
            bogus = str(PydanticObjectId())
            clip_ids = [str(c.id) for c in good] + [bogus]
            created = await client.post(f"{BATCH}/stems", json={"clip_ids": clip_ids}, headers=headers)
            body = created.json()
            print(f"enqueue   -> HTTP {created.status_code}  batch_job_id={body['batch_job_id']}")
            print(f"sub_job_ids: {len(body['sub_job_ids'])} real jobs (the unknown clip has no job)")
            final = await _poll(client, body["batch_job_id"], headers)
            print(f"\noverall_status   : {final['overall_status']}")
            print(f"overall_progress : {final['overall_progress']}")
            print(f"completed/failed : {final['completed_count']}/{final['failed_count']} of {final['total']}")
            print("per-clip status:")
            for s in final["sub_jobs"]:
                extra = f"  -> {len(s['clip_ids'])} stem clips" if s.get("clip_ids") else f"  ({s.get('error')})"
                print(f"  - {s['clip_id']}  {s['status']}{extra}")

            # --- AC2: batch export produces files (real ffmpeg) ----------
            _line("AC2  POST /batch/export: wav + mp3 sources -> flac files")
            wav_clip = await _insert_clip(user, ws, fmt="wav", with_bytes=True)
            mp3_clip = await _insert_clip(user, ws, fmt="mp3", with_bytes=True)
            exp = await client.post(
                f"{BATCH}/export",
                json={"clip_ids": [str(wav_clip.id), str(mp3_clip.id)], "format": "flac"},
                headers=headers,
            )
            ebody = exp.json()
            print(f"enqueue   -> HTTP {exp.status_code}  batch_job_id={ebody['batch_job_id']}")
            efinal = await _poll(client, ebody["batch_job_id"], headers)
            print(f"overall_status   : {efinal['overall_status']}  ({efinal['completed_count']}/{efinal['total']})")
            storage = get_storage_backend()
            batch_doc = await BatchJob.get(PydanticObjectId(ebody["batch_job_id"]))
            from acemusic.api.models import Job

            for s in efinal["sub_jobs"]:
                job = await Job.get(PydanticObjectId(s["job_id"]))
                key = (job.result or {}).get("export_path")
                data = storage.download(key)
                marker = data[:4]
                src_fmt = next(c.format for c in [wav_clip, mp3_clip] if str(c.id) == s["clip_id"])
                print(f"  - {src_fmt:>3} source -> {s['status']}  {len(data)} bytes  marker={marker!r}  (fLaC = valid FLAC)")
            print(f"\nbatch operation field: {batch_doc.operation!r}, target format: {batch_doc.format!r}")

            print("\nAll acceptance criteria demonstrated against the live API.")
    finally:
        await mongo_client.drop_database(settings.mongodb_db_name)
        await database.close_db(mongo_client)


if __name__ == "__main__":
    asyncio.run(main())
