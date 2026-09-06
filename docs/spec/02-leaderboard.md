# 02. 리더보드 & 플레이어 조회

## 리더보드

### API

`GET /leaderboard?board={id}&top={n}`

| 파라미터 | 기본값 | 범위 |
|----------|--------|------|
| `board` | `4` (`TTT2_RANK_BOARD_ID`) | 정수 |
| `top` | `10` | 1 ~ 500 |

### 캐싱 전략

요청 크기와 무관하게 **항상 상위 500건(`LEADERBOARD_CACHE_SIZE`)을 한 번 조회해 하나의 키로 캐시**하고,
응답 시 `entries[:top]`으로 잘라 준다(TTL 300s). `top`별로 캐시를 나누면 RPCN 호출이 배수로 늘기 때문이다.
이 전체 캐시는 플레이어 조회에서도 재사용된다.

### 응답

```json
{
  "total_records": 12345,
  "last_sort_date": 1710000000,
  "entries": [{
    "rank": 1, "np_id": "...", "online_name": "...", "score": 999,
    "record_date": 1710000000, "has_game_data": true, "comment": "",
    "player_info": {
      "main_char_info": { "char_id": 12, "name": "Jin", "rank_info": {"id": 30, "name": "...", "tier": "..."}, "wins": 0, "losses": 0 },
      "sub_char_info":  { ... }
    }
  }]
}
```

`player_info`는 RPCN이 주는 64바이트 `game_info` 블롭을 `>4B4I` 포맷으로 파싱한 결과다.
메인/서브 캐릭터 각각의 캐릭터 ID·계급·전적을 담는다. 캐릭터 이름은 `TTT2_CHARACTERS`로 해석하고,
미지의 ID는 `Unknown(0x..)`으로 표기해 파싱 실패가 응답을 깨지 않게 한다.

### 화면

- 경로 `/leaderboard`. 캐릭터 초상화(`public/characters/`)와 계급 뱃지(`public/ranks/`)를 함께 표시.
- 아트가 없는 계급(`Tekken Lord`, `Initiate` 등)은 `RankImage`가 로드 실패 시 스스로 제거된다.
  실패 여부는 계급 **이름**을 키로 기억한다(React가 행 간 엘리먼트를 재사용하므로 boolean은 다음 행을 오염시킨다).
- 캐릭터 필터(`leaderboardFilter.ts`), 정렬/개수 컨트롤(`LeaderboardControls`)을 제공한다.
- 상위 1~3위 메달 색상은 `medalColors.ts`, 계급 티어 색은 `tierColors.ts`.

## 플레이어 조회

`GET /players/{npid}` — 세 소스를 합성한다. **RPCN을 새로 호출하지 않는다.**

| 항목 | 출처 |
|------|------|
| `online_status.is_matchmaking` | 캐시된 `/rooms/all`에 해당 npid가 있는지 |
| `online_status.is_online` | 매칭 중이거나, 이력상 `last_seen`이 5분 이내 |
| `online_status.last_seen` | `history` 플레이어 통계 |
| `leaderboard` | 캐시된 전체 리더보드에서 npid 일치 항목(없으면 `null`) |
| `usual_playing_hours_kst` | 이력에서 집계한 주 활동 시간대(KST 시각 리스트) |

캐시가 비어 있으면 `leaderboard`는 `null`이 된다 — 의도된 동작이며, 조회 한 번이 RPCN 부하로 번지지 않게 한다.

FE는 `PlayerHistoryPanel`, `ActiveHoursClock`에서 이 응답과 `GET /history/players/{npid}`를 함께 사용한다.
