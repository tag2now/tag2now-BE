from shared.rpcn_password import derive_rpcn_password


def test_derives_password_with_rpcs3_compatible_pbkdf2_sha3_256():
    assert derive_rpcn_password("rpcs3-password-fixture") == (
        "23F4D93177B51F0F0F030F5635CD999933AEE387CFCB1D1B24B3DEA3CD7608D7"
    )
