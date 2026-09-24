# 07. 로그인 (RPCN 계정)

## 목적

예약과 커뮤니티의 "누가 썼나"를 **RPCN 계정**으로 판별한다. 따로 가입할 필요 없이,
RPCS3에서 쓰는 RPCN 아이디와 비밀번호로 로그인한다.

## 구조 — 검증은 RPCN이, 서명은 이 서버가

```
FE ──POST /auth/login {username, password}──▶ tag2now-BE
                                                 │ POST {StatServerPath}/external/users/verify
                                                 │ X-API-Key: RPCN_EXTERNAL_API_KEY
                                                 ▼
                                          RPCN stat server (rpcn-narco)
                                                 │ {username, online_name, avatar_url, admin, banned}
FE ◀──{access_token, expires_in, user}─── tag2now-BE (JWT 서명)
FE ──Authorization: Bearer <access_token>──▶ 쓰기 API
```

- 비밀번호 검증은 rpcn-narco의 외부 사용자 API(`external/users/verify`)가 맡는다.
  RPCN 쪽에 세션을 만들지 않으므로, 같은 계정으로 RPCS3에 접속해 있어도 충돌하지 않는다.
- 이 서버는 결과를 **HS256 JWT**로 서명해 돌려줄 뿐 **아무것도 저장하지 않는다**(stateless).
  DB, 캐시, 재시작과 무관하게 토큰은 서명과 만료만으로 검증된다.

## 토큰

| 클레임 | 값 |
|--------|-----|
| `sub` | RPCN `username` — **RPCN이 돌려준 표기**. 입력한 대소문자가 아니다 |
| `name` | `online_name` (비어 있으면 `username`) |
| `avatar`, `admin` | RPCN 값 그대로 |
| `iss` | `tag2now` |
| `iat`, `exp` | 발급 시각, 만료 시각(`jwt_ttl_seconds`, 기본 7일) |

- 서명 키는 `JWT_SECRET`이며 **32바이트 이상**이어야 한다. 짧거나 비어 있으면 로그인과 인증이 필요한 라우트가 모두 502다.
- `alg: none`이나 다른 키로 서명한 토큰, 만료된 토큰은 401이다.

### stateless의 대가

- **로그아웃은 FE가 토큰을 버리는 것이 전부다.** 서버 측 무효화 라우트는 없다.
- 로그인 뒤에 RPCN에서 밴된 계정도 **토큰이 만료될 때까지는** 쓰기가 가능하다.
- 전원을 강제로 로그아웃시키는 유일한 방법은 `JWT_SECRET` 교체다.

## API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/auth/login` | `{username, password}` → `{access_token, token_type: "bearer", expires_in, user}` |
| GET | `/auth/me` | 토큰의 사용자 `{username, online_name, avatar_url, admin}` |

| 상황 | 상태 | `detail` |
|------|------|----------|
| 아이디/비밀번호 불일치 | 401 | 아이디 또는 비밀번호가 올바르지 않습니다. |
| 밴된 계정 | 403 | 이용이 제한된 계정입니다. |
| RPCN 연결 불가·API 키 오류·미설정 | 502 | 로그인 서버에 연결할 수 없습니다. … / 로그인이 설정되지 않았습니다. |
| 토큰 없음 | 401 | 로그인이 필요합니다. |
| 토큰 만료 | 401 | 로그인이 만료되었습니다. 다시 로그인해 주세요. |
| 토큰 위조·손상 | 401 | 로그인 정보가 올바르지 않습니다. 다시 로그인해 주세요. |

모든 401 응답은 `WWW-Authenticate: Bearer` 헤더를 단다. RPCN이 아이디의 존재 여부를 알려주지 않으므로
(없는 아이디도 401), 이 서버도 둘을 구분하지 않는다. RPCN의 403(API 키 불일치)과 404(API 꺼짐)는
배포 설정 문제이므로 사용자에게는 502로 보이고 서버 로그에 남는다.

## 다른 모듈에서 쓰는 법

라우터는 `auth.dependencies`의 의존성만 쓴다. 토큰을 직접 해석하지 않는다.

```python
from auth.dependencies import current_user      # 없으면 401
from auth.models import AuthUser

@router.post("/things")
async def create(req: Req, user: AuthUser = Depends(current_user)): ...
```

`optional_user`는 토큰이 없으면 `None`을 돌려주되, **잘못된 토큰은 여전히 401**이다.

FastAPI는 의존성을 body 검증보다 먼저 풀기 때문에, 로그인이 필요한 라우트에 토큰 없이 잘못된 body를 보내면
422가 아니라 401이 먼저 나간다.

### 식별자

| 쓰임 | 값 |
|------|-----|
| 소유권 비교 | `user.username` (고유, 변경 불가) |
| 예약 화면 표시 이름 | `user.online_name` |
| 커뮤니티 `author` | `user.username` — 게시판은 이름 하나로 표시와 소유권을 겸하므로 고유한 쪽을 쓴다 |

## 설정

| 설정 | 설명 |
|------|------|
| `RPCN_STAT_URL` | stat server 기준 URL, `StatServerPath`까지 포함 (예: `http://127.0.0.1:31314/rpcn_stats`) |
| `RPCN_EXTERNAL_API_KEY` | rpcn.cfg의 `ExternalUserApiKey`와 같은 값 |
| `RPCN_STAT_TIMEOUT_SECONDS` | 기본 5초 |
| `JWT_SECRET` | HS256 서명 키, 32바이트 이상 |
| `JWT_TTL_SECONDS` | 기본 604800 (7일) |

stat server는 **평문 HTTP**다. 비밀번호와 API 키가 지나가므로 BE와 같은 호스트의 `127.0.0.1`로 붙거나,
HTTPS 리버스 프록시를 거쳐야 한다. 인터넷에 그대로 노출된 HTTP 주소를 넣지 않는다.

비밀값 두 개는 `SecretStr`이라 기동 시 설정 덤프 로그에 `**********`로 찍힌다.
