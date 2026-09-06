# 06. 공통 규약 (Cross-cutting)

## 캐시

`shared/cache.py`가 `CacheBackend` ABC와 두 구현을 제공하고, 임포트 시점에 `redis_url` 설정 하나로 고른다.

| 백엔드 | 선택 조건 | 특성 |
|--------|-----------|------|
| `RedisCache` | `redis_url` 설정됨 | 운영용. Redis 예외를 전부 삼키고 경고 로깅 → 장애가 500이 아니라 캐시 미스로 degrade |
| `DictCache` | `redis_url` 빈 값(기본) | 프로세스 내 dict + 항목별 TTL. 프로세스와 함께 사라진다 |

- `cache_get` / `cache_set(key, value, ttl)` — JSON 왕복. `_DataclassEncoder`가 dataclass와 `datetime`을 처리.
- `cache_delete_pattern(pattern)` — Redis는 `SCAN`(운영 안전), dict는 `fnmatch`.
- 서비스 표준 패턴은 read-through이고, **쓰기 시 무효화는 라우터가 소유**한다.

### TTL (모두 설정값)

| 설정 | 기본 | 대상 |
|------|------|------|
| `cache_ttl_servers` | 3600 | 서버/월드 트리 |
| `cache_ttl_leaderboard` | 300 | 리더보드 500건 |
| `cache_ttl_rooms_all` | 10 | 전체 방 목록 |
| `cache_ttl_community` | 30 | 게시글 목록/상세 |
| `cache_ttl_activity` | 300 | 통계 집계 |
| `cache_ttl_player_hours` | 300 | 플레이어 통계 |
| `matchmaking_ttl` | 60 | 매치메이킹 감지 만료 |

**주의**: `DictCache`는 프로세스별이라 재시작하면 캐시가 전부 날아간다. 로컬에는 적절하지만 운영에는 부적절하다.

## 에러 규약

도메인 코드는 `shared/exceptions.py`의 예외를 던지고, `app.py`가 상태 코드로 매핑한다.
**서비스에서 `HTTPException`을 던지지 않는다.**

| 예외 | 상태 |
|------|------|
| `NotFoundError` | 404 |
| `ForbiddenError` | 403 |
| `ValidationError` | 400 |
| `ServiceUnavailableError` (← `RpcnUnavailableError`) | 502 |

FastAPI의 `RequestValidationError`는 422를 유지하되 응답을 재구성한다.
기본 에러 배열 대신 `_FIELD_LABELS`로 **사용자가 화면에서 볼 수 있는 이름**을 넣은 한국어 한 문장을 반환한다.
새 요청 필드를 추가하면 이 맵에도 넣어야 한다 — 누락되면 "입력값을 확인해 주세요."라는 일반 문구로 떨어진다.

FE는 `main.tsx`에 전역 `unhandledrejection` 핸들러를 두어 토스트로 표시하고 `preventDefault()` 한다.
인라인 에러 상태가 필요한 훅은 스스로 `catch`해 `e.message`를 보관한다.

## RPCN 클라이언트 수명주기

- `matching/rpcn_lifecycle.py`가 `threading.Lock` 뒤에서 **단일 `RpcnClient`** 를 관리한다(소켓이 동시성 안전하지 않다).
- 사용은 반드시 `with api_client() as client:` 컨텍스트 매니저로.
- `RpcnError` / `OSError` 발생 시 연결 해제 → 싱글턴 제거 → `RpcnUnavailableError`.
- 재연결 폭주 방지를 위한 5초 쿨다운(`_RECONNECT_COOLDOWN`).
- `rpcn_metric_enable`이 켜지면 `TrackedRpcnClient`(타이밍 래퍼)로 감싼다.
- RPCN은 **계정당 세션 1개**다. 서버와 통합 테스트를 동시에 돌릴 수 없다.

### 프로토콜 요약 (`rpcn_client/`)

FastAPI 의존성이 없는 독립 패키지. `python -m rpcn_client`로 단독 실행 가능.

- 15바이트 리틀엔디언 헤더(`<BHIQ`): `pkt_type`(0=Request,1=Reply,2=Notification,3=ServerInfo), `cmd`, `total_size`, `packet_id`.
- 단순 명령(서버·월드 목록)은 raw `struct.pack`, 복합 명령(방·스코어)은 u32 LE 길이 접두 protobuf.
- 응답 루프는 `PKT_NOTIF`(친구 상태, 방 이벤트 등 비동기 푸시)를 **조용히 버린다**. 그러지 않으면 요청/응답 쌍이 깨진다.
- RPCN이 자체 서명 인증서를 쓰므로 TLS는 `CERT_NONE`.
- 게임 통신 ID는 정확히 12 ASCII 바이트. TTT2는 `NPWR02973_00`, 랭크 보드 ID는 `4`.

## FE 데이터 흐름

- `shared/util/api.ts`가 **유일한 `fetch` 호출 지점**. base URL은 `window.__ENV__?.API_BASE ?? '/api'`
  (배포 후 재빌드 없이 엔드포인트 교체 가능). 비 2xx는 예외.
- 폴링은 `shared/hooks/usePolledData.ts`로 일원화: `{ data, loading, refreshing, error, refresh, lastUpdated }`.
  최초 로드(`loading`)와 백그라운드 갱신(`refreshing`)을 구분해 폴링마다 화면이 비지 않는다.
  `null` 간격은 1회 조회를 뜻한다.
- `App.tsx`가 `useRooms()`(5초)와 `useLeaderboard()`를 소유하고 하위로 내려준다. 탭 전환은 표시만 바꾼다.
- **URL이 곧 내비게이션 상태다.** `tab` state가 없고 `useActiveTab`이 `useLocation()`에서 파생한다.
  `config/routes.ts`가 "이 탭의 URL은 무엇인가"에 대한 단일 답이다.
- 탭 바는 ARIA tabs 패턴(`role="tablist"/"tab"/"tabpanel"`, roving tabIndex, 좌우 방향키)을 구현한다.

## 설정

`shared/settings.py`의 pydantic-settings 모델. `env/.env` + `env/.env.{profile}`에서 로드하며
프로필은 `FAST_API_PROFILE`(기본 `local`)이 정한다. `get_settings()`는 `@lru_cache` — 프로세스당 1회 읽는다.

| 환경 | 공급 방식 | 프로필 |
|------|-----------|--------|
| 로컬 venv | `env/.env.local` | `local` |
| docker compose | `env_file: env/.env.dev`가 실제 환경변수로 주입 | 미사용 |
| 운영 | 인스턴스의 `.env.prod` | 미사용 |

필수(기본값 없음): `rpcn_user`, `rpcn_password`, `rpcn_token`.
env 파일은 이미지에 굽지 않는다 — `env/.env.example`만 추적되고 Dockerfile은 `env/`를 복사하지 않는다.

## 테스트

| 대상 | 명령 | 외부 의존 |
|------|------|-----------|
| BE 단위 | `pytest tests/unit/` | 없음 |
| BE 통합 | `pytest tests/integration/` | Redis + PostgreSQL(`compose.test.yml`), 일부는 실 RPCN 자격증명 |
| FE 단위/컴포넌트 | `npm test` (Vitest + Testing Library) | 없음 |
| FE E2E | `npm run test:e2e` (Playwright, chromium + Pixel 5) | 없음 — `e2e/helpers/mock-api.ts`가 전 엔드포인트 인터셉트 |
| FE 시각 회귀 | `e2e/visual/` | **로컬 전용** — 베이스라인이 저장소에 없어 CI에서 제외 |

E2E에서 폴링을 실시간으로 기다리지 않는다. 첫 네비게이션 전에 `page.clock`을 설치하고
`runFor`가 아니라 `fastForward`를 쓴다(중간 타이머 콜백을 전부 재생하지 않아 훨씬 빠르다).

## 배포 / 릴리스

- 두 저장소 모두 **`v*` 태그 푸시가 릴리스**다. GitHub Actions가 ECR에 이미지를 올리고 SSH로 Lightsail에 배포한다.
- BE 배포는 `.env.prod`의 `BE_IMAGE_TAG`를 갱신 → `alembic upgrade head` → `be`만 재시작.
- FE 배포는 `FE_IMAGE_TAG` 갱신 → `fe`만 재시작. 두 서비스는 독립 릴리스된다.
- `compose.prod.yml`은 **tag2now-BE가 소유**하며 배포 시 인스턴스로 scp된다. 인스턴스에서 직접 고치지 않는다.
- FE 버전의 단일 출처는 `src/config/patchNotes.ts`의 최상단 항목(`LATEST_PATCH_VERSION`).
  헤더 버전 표기와 패치노트 다이얼로그 재노출을 동시에 좌우한다. 릴리스 태그 `v{version}`만 수동으로 맞춘다.
- `/api` 트래픽은 CloudFront를 거치지 않고 인스턴스로 직접 간다. 정적 자산만 CDN을 탄다.
- 분석은 GA4(`G-S4Y67MPNPR`) 하나뿐이다. SPA 라우트 변경은 `page_view`로 잡히지 않는다(gtag에 history 리스너가 없다).
