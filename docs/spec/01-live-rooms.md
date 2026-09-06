# 01. 실시간 방 목록 & 매치메이킹 감지

## 목적

RPCN에 현재 존재하는 TTT2 방을 모아 "지금 누가 무슨 매치를 잡고 있는지"를 보여준다.
게임 클라이언트를 켜지 않고도 대전 상대가 있는지 확인하는 것이 서비스의 1차 가치다.

## 데이터 획득

1. `GET /servers` — RPCN의 서버 → 월드 계층을 조회한다(`{server_id: [world_id...]}`). 변동이 거의 없어 TTL 3600s로 캐시한다.
2. 모든 월드 ID를 모아 `SearchRoomAll`로 **숨김 방 포함** 전체 방을 조회한다.
3. 각 방의 `int_attrs[4]` 값으로 방 종류를 판별한다.
   - `0` → `player_match` (플레이어 매치, 계급 없음)
   - `0` 이외 → `rank_match` (랭크 매치, 해당 값이 계급 ID)
4. 계급 ID는 `matching/constants.py:TEKKEN_RANKS`로 이름/티어를 해석한다.

### 응답 형태 (`GET /rooms/all`)

```json
{
  "rank_match":   [ RoomInfoDTO, ... ],
  "player_match": [ RoomInfoDTO, ... ]
}
```

`RoomInfoDTO` 필드: `room_id`, `owner_npid`, `owner_online_name`, `current_members`, `max_slots`,
`room_type`, `rank_info{ id, name, tier }`, `users[{ user_id, online_name, avatar_url }]`.

랭크 매치 그룹은 계급 ID 오름차순으로 정렬한다. 캐시 TTL은 10초(`cache_ttl_rooms_all`).

## 매치메이킹 감지 (팬텀 룸)

RPCN은 "매칭 검색 중" 상태를 노출하지 않는다. TTT2 클라이언트는
`searchRoom → createRoom → 대기 → quit` 루프를 돌기 때문에, 검색 중인 플레이어는
자기 방이 존재하는 짧은 순간에만 보인다.

`matching/matchmaking_tracker.py`가 연속 스냅샷을 diff해서 이를 추론한다.

| 규칙 | 동작 |
|------|------|
| 직전 스냅샷에 있던 `RANK_MATCH` 방이 사라짐 (인원 2명이 아님) | 방장을 "검색 중"으로 등록, `MatchmakingDetected` 발행 |
| 인원 2명인 랭크 방은 대전 중(`is_gaming`) | 검색 중으로 보지 않음 |
| 다시 실제 방에 등장 | 검색 목록에서 제거, `MatchmakingResolved` 발행 |
| `matchmaking_ttl`(기본 60s) 동안 재등장 없음 | 만료 제거 |

검색 중인 플레이어는 `RoomInfoDTO.phantom()`으로 만든 가짜 방(`room_id=0`, `current_members=1`, `max_slots=2`)으로
랭크 매치 그룹에 합쳐져 노출된다.

**제약**: 트래커는 모듈 레벨 상태(`_prev_rooms`, `_matchmaking_players`)를 들고 있다.
프로세스가 여러 개면 스냅샷이 갈라져 감지가 어긋난다. 현재 단일 프로세스 배포가 전제 조건이다.

## 화면 (FE)

- 경로: `/match/:group` — `group`은 `rank_match` | `player_match`.
- 탭 스트립은 **응답이 아니라 고정 레이아웃**에서 나온다. `GROUP_ORDER`(랭매, 플매)가 항상 렌더되고,
  API가 새 그룹을 반환하면 뒤에 덧붙는다. 방 데이터는 탭 라벨의 개수 표시에만 영향을 준다.
- 첫 로드 전에는 개수를 `(0)`이 아니라 `(—)`로 표시한다. "아직 모름"과 "0개"를 구분하기 위해서다.
- 5초 주기 폴링(`usePolledData`). 백그라운드 갱신 중에는 화면을 비우지 않고 `refreshing`만 표시한다.
- 랭크 매치는 계급 이미지와 함께, 플레이어 매치는 인원/방장 기준으로 표를 나눠 렌더한다(`RankMatchTable`, `PlayerMatchTable`).

## 실패 동작

- RPCN 장애 시 `RpcnUnavailableError` → HTTP **502**. 클라이언트는 직전 데이터를 유지한 채 에러 배너를 띄운다.
- RPCN 세션은 계정당 1개다. 같은 `RPCN_USER`로 로컬 서버와 테스트를 동시에 돌리면 `LoginAlreadyLoggedIn`으로 실패한다.
