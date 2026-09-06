# tag2now 기능 명세 (Spec)

Tekken Tag Tournament 2(TTT2)의 RPCN 온라인 현황을 보여주는 웹 서비스.
`tag2now-BE`(FastAPI)가 RPCN 서버에서 데이터를 수집·가공하고, `tag2now-FE`(React SPA)가 이를 표시한다.

- 서비스 주소: https://match.tag2now.click
- UI 언어: 한국어 / 시간대 기준: KST(Asia/Seoul)
- 이 문서는 **현재 구현된 동작**을 기술한다. 계획이나 제안이 아니다.
- 문서는 `tag2now-BE` 저장소에 있지만 두 저장소를 함께 다룬다.
  경로 표기 중 `src/app.py`·`matching/`처럼 백엔드 모듈은 이 저장소 기준,
  `src/config/routes.ts`·`shared/util/api.ts`처럼 TypeScript 파일은 `tag2now-FE` 저장소 기준이다.

## 문서 목록

| 문서 | 다루는 기능 |
|------|-------------|
| [01-live-rooms.md](01-live-rooms.md) | 실시간 방 목록, 매치메이킹 감지(팬텀 룸), 탭 구성 |
| [02-leaderboard.md](02-leaderboard.md) | 랭킹 보드, 캐릭터/계급 정보, 플레이어 조회 |
| [03-statistics.md](03-statistics.md) | 접속 통계 수집·집계, 주간 top, 개요(Overview) 탭 |
| [04-reservation.md](04-reservation.md) | 매치 예약 등록·참가·수정·취소, 토큰 소유권 |
| [05-community.md](05-community.md) | 게시판 글·댓글·추천, 익명 식별 |
| [06-cross-cutting.md](06-cross-cutting.md) | 캐시, 에러 응답, 폴링, 배포·릴리스 |

## 시스템 구성

```
RPCS3 유저 ──▶ RPCN 서버 (바이너리 프로토콜, TLS)
                    ▲
                    │ rpcn_client (단일 세션, 스레드 락)
              ┌─────┴──────────────────────────────┐
              │ tag2now-BE (FastAPI)               │
              │  matching / history /              │
              │  community / reservation           │
              │  + shared(cache, events, security) │
              └─────┬───────────────┬──────────────┘
                    │               │
             Redis(캐시)      PostgreSQL(이력·게시판·예약)
                    │
              tag2now-FE (React SPA, nginx) ──▶ 브라우저
```

- 백엔드 도메인 모듈은 헥사고날 구조(`ports.py` / `adapters/` / `service.py` / `router.py`)를 따른다.
- 모듈 간 결합은 인프로세스 이벤트 버스(`shared/events.py`)로 끊는다. `matching` → `history` 방향의 스냅샷 전달이 유일한 사용처다.
- 프로덕션은 AWS Lightsail 단일 인스턴스의 docker compose(`fe`, `be`, `redis`, `postgres`, `dynamodb-local`)다. 단일 프로세스를 전제로 한 모듈 레벨 상태(매치메이킹 트래커, RPCN 클라이언트 싱글턴)가 있으므로 수평 확장은 현재 불가하다.

## 기능 한눈에 보기

| # | 기능 | 화면(FE) | 주요 API(BE) |
|---|------|----------|--------------|
| 1 | 실시간 방 목록 | `/match/:group` | `GET /rooms/all`, `GET /servers` |
| 2 | 리더보드 | `/leaderboard` | `GET /leaderboard` |
| 3 | 플레이어 조회 | 리더보드/통계 내 패널 | `GET /players/{npid}`, `GET /history/players/{npid}` |
| 4 | 통계 | `/stats` | `GET /history/stats`, `/stats/daily`, `/stats/weekly-top` |
| 5 | 예약 | `/reservation`, `/reservation/:id` | `/reservations` CRUD |
| 6 | 커뮤니티 | `/community`, `/community/:postId` | `/community/posts` 등 |
| 7 | 개요 | `/` | 위 항목들의 요약 조합 |
