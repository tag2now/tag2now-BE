# 03. 접속 통계 (History)

## 수집

관측 데이터는 **서로 독립적인 두 경로**로 쌓인다. 하나가 죽어도 다른 하나가 남는다.

### (a) 이벤트 버스 — 요청에 편승

```
matching.service._fetch_rooms_all()
  → publish(ActivitySnapshot(rooms))
    → history.event_handlers._handle_activity_snapshot()
      → history.service.record_snapshot()
```

`/rooms/all`이 **캐시 미스로 실제 조회**될 때만 발행된다. 즉 방문자가 있을 때의 관측이다.

핸들러는 인원 2명인 랭크 방(= 대전 성사)만 골라내고, 그중 **직전 관측에 없던 방(신규)** 만 기록한다.
같은 대전이 폴링마다 중복 적재되는 것을 막기 위해 `_prev_gaming_room_ids`를 모듈 상태로 들고 비교한다.
핸들러 예외는 로깅만 하고 발행자에게 전파하지 않는다(통계 실패가 방 목록을 깨지 않는다).

### (b) 수집기 — 자체 클럭

`history/collector.py`가 lifespan에서 백그라운드 asyncio 태스크로 뜬다.
`match_history_collection_interval_seconds`(기본 30s)마다:

1. `matching.service.collect_activity_observation()` — HTTP 응답 캐시를 **우회**해 RPCN에서 직접 조회
2. 랭크 방(인원 1명 이상) 참가자 npid 집합을 `record_daily_matched_players()`로 기록
3. 전체/랭크의 인원 수·방 수를 `record_activity_snapshot()`으로 기록

수집은 방문자 유무와 무관하게 돌아야 하므로 응답 캐시를 타지 않는다.
한 사이클이 실패해도 로깅 후 건너뛴다. 루프는 절대 죽지 않는다.

## 저장 스키마 (PostgreSQL)

| 대상 | 내용 |
|------|------|
| 방 스냅샷 | `room_id`, `rank_id`, 참가자 2인의 npid/이름, 관측 시각 |
| 활동 스냅샷 | 관측 시각, 총 인원/방 수, 랭크 인원/방 수 |
| 일별 대전 참가자 | 날짜별 유니크 npid 집합 |

마이그레이션은 alembic으로 관리하며, 배포 시 `alembic upgrade head`가 자동 실행된다.

## 집계 API

| 엔드포인트 | 파라미터 | 반환 |
|-----------|----------|------|
| `GET /history/stats` | `days` 1~90 (기본 7) | KST 시간대(0~23)별 평균/최대 접속자 |
| `GET /history/stats/daily` | `days` 1~90 (기본 30) | 일자별 최대/평균 접속자, 최대 방 수, 유니크 대전 참가자 수 |
| `GET /history/stats/weekly-top` | `limit` 1~50 (기본 10) | 최근 7일 관측 빈도 상위 플레이어 (`npid`, `online_name`, `match_count`) |
| `GET /history/players/{npid}` | `days` 1~90 (기본 30) | 활동 일수, 관측 횟수, 최초/최종 목격, 방 종류별 횟수, 자주 만난 상대, 활동 시간대 |

모든 읽기는 read-through 캐시(TTL 300s)를 거친다. 쓰기 경로는 **커밋 이후에** `history:daily:*` 패턴을 무효화한다.

집계는 KST 기준이다. 서버가 UTC로 돌더라도 "오늘"의 경계는 Asia/Seoul이다.

## 화면

### 통계 탭 (`/stats`)

- 시간대별 접속 곡선, 일별 요약 차트(recharts), 주간 상위 플레이어 표.
- 주간 top 응답에는 캐릭터 정보가 없다. 리더보드 데이터를 npid로 조인해 초상화를 채우고,
  리더보드에 없는 플레이어는 열을 지우지 않고 대시(`—`)로 표시한다.
- recharts는 SVG 속성을 그리므로 CSS 변수를 못 읽는다. `chartTheme.ts`가 `@theme` 토큰을 JS 상수로 미러링한다.

### 개요 탭 (`/`, 랜딩)

다른 탭의 요약이자 진입점. 각 카드는 대응 탭으로 링크된다.

- 방·리더보드 데이터는 `App.tsx`가 이미 폴링하므로 **props로 받는다**. 개요가 자체 폴링을 추가하지 않는다.
- 자체 요청은 4건뿐이며 `Promise.allSettled`로 묶는다: 일별 통계, 주간 top, 최신 게시글, 모집 중인 예약.
  하나가 실패하면 그 카드만 비고 페이지는 살아 있다.
- 폴링 간격은 `null`(1회 조회 + 수동 새로고침). 진짜 실시간인 방 수치는 App의 폴링으로 이미 갱신된다.
- KPI "활성 방" 힌트는 `GROUP_ORDER`로 그룹을 되읽는다. `fetchRoomsAll`이 그룹 순서를 셔플하기 때문에
  그러지 않으면 5초마다 KPI 순서가 바뀐다.
