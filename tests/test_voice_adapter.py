"""US-25.4: making a trained voice the active adapter on the ACE-Step host.

The adapter is global handler state, so what these tests pin down is *when* the host
is talked to and that two generations can never overlap while it is being changed.
"""

import asyncio
import json

import httpx
import pytest

from acemusic.api.tasks import voice_adapter
from acemusic.api.tasks.voice_adapter import VoiceAdapterError, _AdapterState, active_voice

BASE_URL = "http://ace-step.test"


def _recording_transport(calls: list[tuple[str, dict]], *, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        calls.append((request.url.path, body))
        return httpx.Response(status_code, json={"code": status_code, "data": {}})

    return httpx.MockTransport(handler)


@pytest.fixture
def calls(monkeypatch) -> list[tuple[str, dict]]:
    """Record every LoRA call the module makes, answering each with 200."""
    recorded: list[tuple[str, dict]] = []
    transport = _recording_transport(recorded)
    original = httpx.AsyncClient
    monkeypatch.setattr(
        voice_adapter.httpx,
        "AsyncClient",
        lambda **kwargs: original(**{**kwargs, "transport": transport}),
    )
    return recorded


class TestAdapterState:
    async def test_a_voice_is_loaded_by_its_adapter_path(self, calls) -> None:
        state = _AdapterState()

        async with state.hold(BASE_URL, "/lora/aria/adapter"):
            pass

        assert calls == [("/v1/lora/load", {"lora_path": "/lora/aria/adapter"})]

    async def test_the_same_voice_twice_running_loads_once(self, calls) -> None:
        state = _AdapterState()

        async with state.hold(BASE_URL, "/lora/aria/adapter"):
            pass
        async with state.hold(BASE_URL, "/lora/aria/adapter"):
            pass

        assert len(calls) == 1

    async def test_a_generation_with_no_voice_unloads_a_previous_one(self, calls) -> None:
        state = _AdapterState()

        async with state.hold(BASE_URL, "/lora/aria/adapter"):
            pass
        async with state.hold(BASE_URL, None):
            pass

        assert [path for path, _ in calls] == ["/v1/lora/load", "/v1/lora/unload"]

    async def test_generation_without_a_voice_never_touches_the_host(self, calls) -> None:
        # A deployment that trains no voices should pay nothing for this module.
        state = _AdapterState()

        async with state.hold(BASE_URL, None):
            pass
        async with state.hold(BASE_URL, None):
            pass

        assert calls == []

    async def test_switching_between_two_voices_reloads(self, calls) -> None:
        state = _AdapterState()

        async with state.hold(BASE_URL, "/lora/aria/adapter"):
            pass
        async with state.hold(BASE_URL, "/lora/rex/adapter"):
            pass

        assert [body.get("lora_path") for _, body in calls] == [
            "/lora/aria/adapter",
            "/lora/rex/adapter",
        ]

    async def test_a_rejected_load_fails_the_generation(self, monkeypatch) -> None:
        recorded: list[tuple[str, dict]] = []
        transport = _recording_transport(recorded, status_code=400)
        original = httpx.AsyncClient
        monkeypatch.setattr(
            voice_adapter.httpx,
            "AsyncClient",
            lambda **kwargs: original(**{**kwargs, "transport": transport}),
        )
        state = _AdapterState()

        with pytest.raises(VoiceAdapterError):
            async with state.hold(BASE_URL, "/lora/aria/adapter"):
                pytest.fail("the body must not run when the adapter could not be set")

    async def test_a_failed_load_is_retried_rather_than_assumed(self, monkeypatch) -> None:
        # A failure leaves the host in an unknown state; the next generation must say
        # what it wants again instead of trusting a cached answer.
        recorded: list[tuple[str, dict]] = []
        outcomes = iter([500, 200])

        def handler(request: httpx.Request) -> httpx.Response:
            recorded.append((request.url.path, {}))
            return httpx.Response(next(outcomes), json={})

        original = httpx.AsyncClient
        monkeypatch.setattr(
            voice_adapter.httpx,
            "AsyncClient",
            lambda **kwargs: original(**{**kwargs, "transport": httpx.MockTransport(handler)}),
        )
        state = _AdapterState()

        with pytest.raises(VoiceAdapterError):
            async with state.hold(BASE_URL, "/lora/aria/adapter"):
                pass
        # Without the retry this would be skipped as "already on the base model" — but
        # the failed load may have landed, so the base model has to be asked for.
        async with state.hold(BASE_URL, None):
            pass

        assert [path for path, _ in recorded] == ["/v1/lora/load", "/v1/lora/unload"]

    async def test_generations_wanting_different_voices_never_overlap(self, calls) -> None:
        """The whole point: nothing else may run while the adapter is being changed."""
        state = _AdapterState()
        live: list[str | None] = []
        seen: list[list[str | None]] = []

        async def run(weights: str | None) -> None:
            async with state.hold(BASE_URL, weights):
                live.append(weights)
                # Two suspension points, so an interleaving would be observed.
                await asyncio.sleep(0)
                seen.append(list(live))
                await asyncio.sleep(0)
                live.remove(weights)

        await asyncio.gather(run("/lora/aria/adapter"), run(None), run("/lora/rex/adapter"))

        for concurrent in seen:
            assert len(set(concurrent)) == 1, f"two different voices were live at once: {concurrent}"

    async def test_a_queued_voice_is_not_starved_by_steady_base_traffic(self, calls) -> None:
        """A switch already queued goes next, ahead of arrivals the loaded adapter suits.

        Without this, a generation asking for a voice waits behind an unbounded stream of
        plain generations — each of which matches the loaded (base) adapter — and never
        sees the host go quiet.
        """
        state = _AdapterState()
        started: list[str] = []
        running = asyncio.Event()
        finish = asyncio.Event()

        async def hold_open() -> None:
            async with state.hold(BASE_URL, None):
                started.append("first-plain")
                running.set()
                await finish.wait()

        async def queued(label: str, weights: str | None) -> None:
            async with state.hold(BASE_URL, weights):
                started.append(label)

        first = asyncio.create_task(hold_open())
        await running.wait()

        # Queued while the host is busy: the voice first, then more plain traffic.
        wants_voice = asyncio.create_task(queued("voice", "/lora/aria/adapter"))
        await asyncio.sleep(0)
        later_plain = [asyncio.create_task(queued(f"plain-{i}", None)) for i in range(3)]
        await asyncio.sleep(0)

        finish.set()
        await asyncio.gather(first, wants_voice, *later_plain)

        assert started[1] == "voice", f"the queued voice was overtaken: {started}"

    async def test_generations_sharing_a_voice_still_run_concurrently(self, calls) -> None:
        """Voices must not cost the throughput that plain generation had."""
        state = _AdapterState()
        live = 0
        peak = 0

        async def run() -> None:
            nonlocal live, peak
            async with state.hold(BASE_URL, None):
                live += 1
                peak = max(peak, live)
                await asyncio.sleep(0)
                live -= 1

        await asyncio.gather(run(), run(), run())

        assert peak == 3


class TestActiveVoice:
    async def test_a_backend_without_lora_support_rejects_a_voice(self) -> None:
        with pytest.raises(VoiceAdapterError, match="local compute"):
            async with active_voice(None, "/lora/aria/adapter"):
                pytest.fail("a voice must not be silently dropped")

    async def test_a_backend_without_lora_support_runs_plain_generations(self) -> None:
        ran = False
        async with active_voice(None, None):
            ran = True
        assert ran
