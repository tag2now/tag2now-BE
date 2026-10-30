# tag2now-BE 리팩터링 인계 — 2026-10-23

새 세션에서 이 문서부터 읽고 이어서 진행한다. 리팩터링이 끝나면 이 파일을 지우는 커밋으로 마무리한다.
경로는 워크스페이스 루트(`D:/project/tag2now`) 기준으로 적었다. "이 PC"라고 적은 항목은
원래 작업하던 Windows 머신의 로컬 상태라서 다른 머신에서는 해당하지 않을 수 있다.

---

## 0. 지금 상태 (가장 먼저 확인)

- **E6b까지 모두 커밋됨** (`609ffee`). 다음은 **E7 계획을 보여주는 것**부터.
  워크스페이스 루트 `CLAUDE.md`도 이번 작업 중 한 줄 바뀌었다(git 밖).
- origin에는 `de5750b`(이 문서)까지 올라가 있고, 그 뒤 커밋은 **push하지 않았다.** push는 사용자가 따로 요청할 때만.
- (이 PC) Docker Desktop은 하루 지나면 꺼져 있을 수 있다. Git Bash에서 띄우면 셸과 함께 죽으니
  PowerShell `Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"`로 띄운다.

## 1. 진행 방식 (사용자 합의 사항)

- 응답은 한국어. 코드·경로·커밋 메시지는 영어.
- **각 단계마다 계획을 먼저 보여주고 승인 후 작업.** "계획부터 보여라, 바로 작업하지 말라"고 명시함.
- **커밋 경계에서 멈추고 커밋 여부를 묻는다.** 커밋은 요청이 있을 때만, master에 직접. push는 별도 승인.
- 용어(seam, composition root 등)는 써도 되지만 **처음 나올 때 설명**한다.
  FastAPI 고유 방식(Depends, dependency_overrides, lifespan state)을 기존 코드와 비교해 제시한다.
- 테스트는 `tag2now-BE/.claude/skills/test/SKILL.md` 순서 그대로, 로그를 `test-results/`에 통째로 남기고
  실패는 그 첫 실행에서 이름을 댄다. 재실행은 `--last-failed`만.
  ```bash
  .venv/Scripts/python.exe -m pytest tests/unit/ -v > test-results/unit.log 2>&1
  docker compose -f compose.test.yml up -d --wait
  DATABASE_URL=postgresql+psycopg://tag2now:tag2now@127.0.0.1:5433/tag2now .venv/Scripts/python.exe -m alembic upgrade head > test-results/migrate.log 2>&1
  .venv/Scripts/python.exe -m pytest tests/integration/ -v > test-results/integration.log 2>&1
  .venv/Scripts/ruff.exe check . > test-results/lint.log 2>&1
  ```
- integration은 `-m "not rpcn"` 없이 147개 전부 돌린다. rpcn 마커 테스트는 `.env.local`의 로컬 계정으로 접속하므로
  **실행 중인 uvicorn(dev 서버)만 먼저 끄면** 된다(운영과는 다른 계정). 확인 명령은 테스트 스킬 4단계.
- 커밋 메시지는 짧게, 사용자 관점의 변화를 쓴다. 동작이 그대로면 "behaves exactly as before".
- 들여쓰기 3단계 초과 금지, 불필요한 분기 금지, private 메서드 테스트 금지 (전역 CLAUDE.md).

## 2. 이미 끝난 것 (BE master 로컬 커밋, 오래된 순)

| 커밋 | 내용 |
|---|---|
| f14a1cb | P1: 비밀번호 PBKDF2(220ms)를 `asyncio.to_thread`로 — 이벤트 루프 블로킹 제거 |
| e32e5d8 | 문서 사실 오류 수정(운영 구성, CloudFront 경로 등) |
| 6c3dc76 | C2: 안 쓰는 `GET /players/{npid}` 등 죽은 코드 제거 |
| 1812f9b | C1: DynamoDB 커뮤니티 백엔드 제거 |
| 8fab18d | F1: 탭→스페이스 (`.git-blame-ignore-revs`에 등록됨) |
| dd4aced | F2: `ruff check`(F 규칙만) + CI lint job (ruff 0.17.1 고정) |
| 3eb1978 | A: `cache_delete(key)` — 알려진 키를 glob이 아니라 글자 그대로 삭제 |
| f985e3e | B: community 캐시·무효화를 router→service |
| 43d44f2 | C: community Postgres 어댑터 가독성 정리 |
| df3dd67 | D: TTT2 상수를 `shared/ttt2.py`로 |
| ec74025 | G: 낡은 docstring, DB_URL 설명, pyproject 의존성 |
| 7045bab | E1: `src/container.py`(composition root) + lifespan `AsyncExitStack` + community를 Depends로 |
| 03ca741 | E2: reservation + `shared/clock.py` |
| e94c7ae | E3: saves |
| a1d01db | E4: auth·admin (공유 `RpcnApiClient`를 container가 소유) |
| 4712404 | E5: streaming (세션을 서비스가 직접 염) |
| 5ef2ed4 | E6a: matching + tracker 인스턴스화 + `/rooms/all` router 조합 + Collector 클래스 |
| 609ffee | E6b: RPCN 연결을 `SharedRpcnClient(client_factory)` 인스턴스로, container가 생성. 재접속·쿨다운 단위 테스트 |

## 3. E 단계의 목표 구조 (확정된 설계)

- **composition root** = `src/container.py`의 `build_container(stack)`. 서버 시작 시 lifespan이 한 번 호출해
  모든 어댑터·서비스를 만들고 `Container` dataclass에 담는다. lifespan은 `app.state.container`에 둔다.
  각 자원의 close는 `AsyncExitStack`에 등록 → 종료 시 역순으로 닫히고, 중간 실패 시 연 것만 닫힌다.
- 각 모듈: `service.py`는 포트를 생성자로 받는 **클래스**, `dependencies.py`는
  `request.app.state.container.<이름>`을 돌려주는 provider, `router.py`는 `Depends(provider)`.
- 테스트는 `app.dependency_overrides[provider] = lambda: Service(fake)` 또는 서비스를 직접 생성.
  라우트 테스트 디렉터리마다 `conftest.py`에 autouse 기본 대역(`installed` fixture)을 둔다 —
  **FastAPI는 body/query 검증 에러를 내기 전에 의존성을 먼저 실행**하므로, 422를 기대하는 테스트도 대역이 필요.
  `tests/unit/test_validation_messages.py`의 client fixture에도 옮긴 모듈마다 override를 추가해야 한다.
- 서비스 간 연결: `/rooms/all`은 **router가** matching(방)과 streaming(방송)을 각각 받아 조합한다
  (`players_in` / `with_streams` 순수 함수 + `StreamingService.live_or_empty`). matching은 streaming을 모른다.
- 요청 밖 코드(collector)는 container가 만들어 lifespan이 `container.collector.run()`으로 시작.
- 남기는 전역: `shared.database`의 engine/session factory, `get_settings()`(lru_cache), cache 백엔드.
- 트랜잭션: 서비스가 받은 `sessions`(session factory)로 직접 연다 —
  읽기 `async with self._sessions() as s`, 쓰기 `async with self._sessions() as s, s.begin()`.
- 현재 `container._LIFECYCLES`에 남은 옛 방식 모듈: `init_database`, `init_history_repo`, `init_chat`.

## 4. 남은 작업

### E7 — history (+ Collector에 history 주입)

- `HistoryService(repo, sessions)` 클래스. `@transactional`/`@read_only` 데코레이터 대신 세션 직접 열기(E5와 동일).
  `record_daily_matched_players` 등은 쓰기 후 `cache_delete_pattern("history:daily:*")` 유지.
- `history/dependencies.py`, router Depends. `history/db.py` 삭제, `_LIFECYCLES`에서 `init_history_repo` 제거.
  `history/__init__.py`는 alembic용 `import history.entities`만 남긴다.
- `Collector(matching, history)` — 지금 `history_service` 모듈 함수 호출을 주입받은 서비스로.
- 테스트: `tests/unit/history/conftest.py`, collector unit/integration 테스트(history_service 모듈 패치 → 가짜 history 주입),
  history 어댑터 integration 테스트, `test_container`, `test_validation_messages`(history 라우트 쓰면).
- 이후 `shared/database.py`의 `transactional`/`read_only`를 쓰는 곳이 없으면 삭제.

### E8 — chat

- `ChatService(repo, bus, clock=None)` 클래스. 모듈 전역 `_repo`/`_bus`/`_clock`/`_last_post`(연타 방지)와
  `configure()`가 사라지고 `_last_post`는 인스턴스 상태 → 테스트마다 새 인스턴스면 상태도 새로 시작.
- `chat/ports.py`의 `Clock`을 지우고 `shared.clock` 사용. `chat/db.py`(init_chat) 삭제,
  container가 `PostgresChatRepository(sessions, MAX_LISTED_MESSAGES)` + `MemoryChatEventBus()`로 생성
  (`MAX_LISTED_MESSAGES = 500`과 그 주석을 container 또는 chat 모듈로 옮김).
- SSE 라우트 `GET /chat/stream`도 `Depends(chat_service)`. 스트림이 오래 열려 있어도 서비스는 container 수명이라 문제없음.
- 테스트: `tests/unit/chat/test_router.py`(configure 4곳), `test_service.py`(2곳), integration `test_postgresql_adapter.py`(init_chat 2곳).

### E9 — 마무리

- `_LIFECYCLES`에 `init_database`만 남으면 튜플을 없애고 `build_container`에서 직접 열고 close 등록. `test_container` 갱신.
- BE CLAUDE.md "Hexagonal layering" 절에서 "Migration in progress" 문단 제거, 최종 구조로 정리.
- BE README 구조 설명(모듈 목록·`db.py` 언급) 갱신 여부 확인.
- 메모리 `tag2now-be-refactor-backlog.md` 갱신.

### 리팩터링 맨 마지막 — `ruff format`

사용자 결정: **모든 의미 변경이 끝난 뒤 마지막 커밋으로** `ruff format` 적용 + 그 해시를 `.git-blame-ignore-revs`에 추가.
diff 규모를 먼저 측정해 보여준다(120자 넘는 줄 117개 등, 거의 전 파일 예상).

## 5. 별도 백로그 (E와 무관, 사용자에게 제안만)

- **Redis 테스트 불일치**: 운영은 dict 캐시인데 integration/CI는 Redis로 돈다 → 운영 경로는 unit으로만 검증.
  Redis는 유지하기로 결정함. integration을 dict로 돌리고 Redis 경로를 따로 테스트하는 방안.
- **BE README 정리**: 환경 변수 표 기본값이 실제와 다름(`CACHE_TTL_LEADERBOARD` 60→300, `CACHE_TTL_ROOMS_ALL` 5→10 등),
  endpoint 표·구조 설명 낡음. 갱신 or `/docs`·`docs/spec`로 대체 결정 필요.
- **matchmaking tracker 구동 방식**: HTTP 캐시 미스(방문자 요청)에 끌려 돈다. 방문이 끊겼다 재개되면
  몇 분 전 스냅샷과 비교해 가짜 phantom이 60초 노출. collector와 RPCN 조회도 중복. 단일 poller로 통합 검토.
- **read-through 캐시 보일러플레이트**: `cached(key, ttl, loader)` 헬퍼로 모듈마다 반복되는 코드 축소.
- **tag2now-save-admin 문서 링크**: `docs/TTT2 TDT 세이브 포맷.md` 321행이 BE의 `src/matching/constants.py`를
  링크 — D 커밋(파일 이동) push 후 깨짐. `src/shared/ttt2.py`로 고치는 한 줄 수정(다른 저장소).
- **테스트의 `installed` 상자 정리**: 라우트 테스트 conftest의 autouse `installed` fixture는
  `{"service": 기본 대역}` dict를 두고 `dependency_overrides[provider] = lambda: current["service"]`로 등록한다.
  이유는 둘 — (1) 401/422 테스트도 의존성 해석 때문에 대역이 필요, (2) 진짜 서비스는 테스트 본문에서
  `use_platform(...)` 등으로 정해지므로 override를 다시 등록하지 않고 상자 안 값만 바꾸려는 것.
  문제: `tests/unit/streaming/test_streams.py`에서 `live_for`를 직접 부르는 서비스 테스트 4개가
  라우트용 상자(`installed["service"]`)를 빌려 서비스를 꺼낸다 — 같은 파일의
  `test_when_channels_cannot_be_read_nobody_is_live`는 서비스를 직접 만들어 방식이 섞임. 이름도 의도를 안 드러냄.
  개선안: `use_platform`이 만든 `StreamingService`를 반환(override 갱신은 그 안에서). 지금 반환값(platform)을
  `platform.checked` 검사에 쓰는 테스트가 있으므로, platform을 먼저 변수로 만들어 넘기거나 `(service, platform)`을 반환.
  같은 패턴: saves `use_server`, auth `use_verifier`, admin `use_rpcn`(대부분 라우트 테스트라 덜 심각). E와 별도 커밋.
- (이 PC) 로컬 `tag2now-BE/env/.env.prod`(2026-04 사본)에 DynamoDB 키가 남아 있음 — 어디서도 안 읽음, 삭제 후보.
- (이 PC) 워크스페이스 루트 `HANDOFF.md`(2026-09-08)는 내용이 낡음(x-reservation-token) — 삭제 후보.
- 루트 CLAUDE.md의 CloudFront 로깅 비용 불일치(Free 플랜에서 로깅 잠김) — 콘솔 확인 필요.
