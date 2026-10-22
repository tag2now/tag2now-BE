import asyncio

from shared.rpcn_password import derive_rpcn_password, derive_rpcn_password_in_thread

FIXTURE_DERIVED = "23F4D93177B51F0F0F030F5635CD999933AEE387CFCB1D1B24B3DEA3CD7608D7"


def test_derives_password_with_rpcs3_compatible_pbkdf2_sha3_256():
    assert derive_rpcn_password("rpcs3-password-fixture") == FIXTURE_DERIVED


async def test_deriving_in_a_thread_leaves_the_event_loop_free():
    ticks = 0

    async def tick():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.001)
            ticks += 1

    ticker = asyncio.create_task(tick())
    try:
        derived = await derive_rpcn_password_in_thread("rpcs3-password-fixture")
    finally:
        ticker.cancel()

    assert derived == FIXTURE_DERIVED
    # Run on the loop, the derivation would hold it until done and tick zero times.
    assert ticks >= 3
