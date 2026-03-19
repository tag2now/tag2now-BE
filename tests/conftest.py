import pytest
from rpcn_client import RpcnClient

HOST     = "rpcn.mynarco.xyz"
PORT     = 31313
USER     = "doStudyForAPI"
PASSWORD = "23866C8DAF2A8675DFB90B34A35089A68C813BFDEFB2EC99A0CD532A55BB62BB"
TOKEN    = "2E38DFB84E0ED2A3"


@pytest.fixture(scope="session")
def session():
    c = RpcnClient(HOST, PORT)
    c.connect()
    info = c.login(USER, PASSWORD, TOKEN)
    yield {"client": c, "login_info": info}
    c.disconnect()
