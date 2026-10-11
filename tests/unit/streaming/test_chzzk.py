"""Chzzk ids and the Chzzk adapter, with api.chzzk.naver.com replaced by an httpx mock transport."""

import httpx
import pytest

from streaming.adapters.chzzk import ChzzkPlatform
from streaming.domain import chzzk_live_url, parse_chzzk_channel_id
from streaming.exceptions import StreamingUnavailableError
from streaming.models import LiveBroadcast, PlatformChannel

CHANNEL_ID = "c42cd75ec4855a9edf204a407c3c1dd2"
CHANNEL = {"code": 200, "content": {"channelId": CHANNEL_ID, "channelName": "철권러"}}
UNKNOWN_CHANNEL = {"code": 200, "content": {"channelId": None, "channelName": "(알 수 없음)"}}
LIVE = {"code": 200, "content": {"status": "OPEN", "liveTitle": "TTT2 랭크전", "concurrentUserCount": 42,
                                 "liveCategoryValue": "Tekken Tag Tournament 2"}}
OFFLINE = {"code": 200, "content": {"status": "CLOSE", "liveTitle": "지난 방송", "concurrentUserCount": 3}}


# --- ids ------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    CHANNEL_ID,
    f"https://chzzk.naver.com/{CHANNEL_ID}",
    f"https://chzzk.naver.com/live/{CHANNEL_ID}?from=share",
    f"  chzzk.naver.com/{CHANNEL_ID.upper()}  ",
])
def test_finds_the_channel_id_in_a_url_or_alone(text):
    assert parse_chzzk_channel_id(text) == CHANNEL_ID


@pytest.mark.parametrize("text", ["", "https://chzzk.naver.com/", CHANNEL_ID[:-1], CHANNEL_ID + "0", "철권러"])
def test_finds_nothing_without_exactly_32_hex(text):
    assert parse_chzzk_channel_id(text) is None


def test_links_to_the_live_page():
    assert chzzk_live_url(CHANNEL_ID) == f"https://chzzk.naver.com/live/{CHANNEL_ID}"


# --- adapter --------------------------------------------------------------------

async def _adapter(handler) -> ChzzkPlatform:
    adapter = ChzzkPlatform("https://api.chzzk.test", 1.0, transport=httpx.MockTransport(handler))
    await adapter.init()
    return adapter


def _answer(status: int, body):
    return lambda request: httpx.Response(status, json=body)


async def test_reads_a_channel_with_a_browser_user_agent():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=CHANNEL)

    adapter = await _adapter(handler)
    assert await adapter.channel(CHANNEL_ID) == PlatformChannel(channel_id=CHANNEL_ID, channel_name="철권러")
    assert seen[0].url.path == f"/service/v1/channels/{CHANNEL_ID}"
    assert seen[0].headers["User-Agent"].startswith("Mozilla/5.0")
    await adapter.close()


async def test_an_unknown_channel_is_none_though_it_answers_200():
    adapter = await _adapter(_answer(200, UNKNOWN_CHANNEL))
    assert await adapter.channel(CHANNEL_ID) is None
    await adapter.close()


async def test_an_open_broadcast_is_live():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=LIVE)

    adapter = await _adapter(handler)
    assert await adapter.live(CHANNEL_ID) == LiveBroadcast(title="TTT2 랭크전", viewer_count=42,
                                                         category="Tekken Tag Tournament 2")
    assert seen[0].url.path == f"/polling/v2/channels/{CHANNEL_ID}/live-status"
    await adapter.close()


@pytest.mark.parametrize("status, body", [
    (200, OFFLINE),
    (404, {"code": 404, "message": "채널이 존재하지 않습니다."}),
    (200, {"code": 200, "content": None}),
])
async def test_a_closed_or_missing_channel_is_not_live(status, body):
    adapter = await _adapter(_answer(status, body))
    assert await adapter.live(CHANNEL_ID) is None
    await adapter.close()


@pytest.mark.parametrize("status, body", [(500, {"code": 500}), (200, ["not", "an", "object"]), (403, "blocked")])
async def test_anything_else_is_unavailable(status, body):
    adapter = await _adapter(_answer(status, body))
    with pytest.raises(StreamingUnavailableError):
        await adapter.live(CHANNEL_ID)
    await adapter.close()


async def test_a_network_failure_is_unavailable():
    def handler(request):
        raise httpx.ConnectTimeout("timed out")

    adapter = await _adapter(handler)
    with pytest.raises(StreamingUnavailableError):
        await adapter.channel(CHANNEL_ID)
    await adapter.close()
