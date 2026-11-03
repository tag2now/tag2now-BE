# 11. 전적

누가 누구와 어떤 캐릭터, 어떤 계급으로 게임해서 어떤 결과가 났는지 기록하고 `GET /records/matches`로 보여준다.
화면은 FE의 '전적' 탭과 프로필의 전적 탭이다.

세이브에는 승패와 캐릭터가 있지만 상대가 없고, 방 관측에는 상대가 있지만 승패가 없다. 그래서 세이브 변화로 한 판을
찾고, 그 시각의 방으로 상대를 찾는다. 대상은 랭크 매치뿐이다. 방 관측이 2인 `RANK_MATCH`만 있기 때문이다.

## 전제

- **방은 재사용되지만 구성원은 바뀌지 않는다.** 방 하나가 같은 두 사람의 여러 판을 담는다. 방을 한 판으로 세면 안
  된다. 한 판의 경계는 세이브 변화다.
- **세이브는 누적값이다.** 저장을 놓쳐도 다음 저장과 비교하면 순 승패가 맞는다. 잃는 것은 판 사이의 구분뿐이다.
- 저장의 형식과 시점은 tag2now-save-admin의 세이브 포맷 문서를 따른다. 한 판은 시작 저장과 결과 저장 두 번이고,
  저장의 절반 이상은 전적이 변하지 않는 재업로드다.

## 흐름

```
Collector (30초)      현재 방의 rank_match_snapshots.last_seen_at 갱신

save-admin GET /players/saves?after=&limit=
    ▼ 10초 (SaveCapture, 세이브마다 한 트랜잭션)
save_states 갱신 + 판이 끝났을 때만 match_events 추가
    ▼ FOR UPDATE SKIP LOCKED (EventConsumer)
그 시각의 방에서 상대 조회, 양쪽 연결 → match_results
```

- 세이브 해석은 save-admin, 직전 상태와의 비교는 이 서비스가 맡는다. 비교에는 영속 상태가 필요한데 그것이 이쪽에 있고,
  누적값을 받으면 조회를 놓쳐도 다음 조회에서 복구되기 때문이다.
- 세이브 수집이 10초인 이유: 재대결이면 결과 저장 직후 다음 대전의 시작 저장이 덮어쓴다. 간격이 짧을수록 시작 저장을
  잡아 태그 순서를 얻고 `played_at`도 정확해진다.
- `SaveCapture`와 `EventConsumer`는 `be` 안의 asyncio 태스크다. 수집기와 분리되어 있어 save-admin이 멈춰도 다른 수집은
  계속된다. `SAVE_ADMIN_URL`이 비면 `SaveCapture`는 돌지 않는다.

## 수집과 판정

저장된 최대 `data_id`에서 16을 뺀 값부터 읽는다. id는 행이 커밋되기 전에 발급되므로 작은 id가 나중에 보일 수 있다.
`data_id`가 이미 반영된 값 이하인 세이브는 건너뛴다.

| 직전 대비 변화 | 처리 |
|---|---|
| 직전 상태 없음 | 상태만 저장 (기준선) |
| 승 +1 또는 패 +1 | 상태 갱신, 이벤트 추가 |
| 변화 없음 | 상태만 갱신 |
| 그 외 (여러 판 합침, `restore`로 감소) | 상태 갱신, `merged_count` 증가, 이벤트 없음 |

승패 변화를 시작 저장 여부보다 먼저 본다. 재대결의 결과는 다음 대전의 시작 저장에 함께 실려 올 수 있다.

상태 갱신과 이벤트 추가는 한 트랜잭션이다(트랜잭셔널 아웃박스). 이벤트만 빠지거나 상태만 앞서가는 일이 없다.

**캐릭터:** 이번 변화에서 승(패배면 패)이 오른 캐릭터가 그 판의 캐릭터다. 직전 상태가 시작 저장이고 그 `own_chars`가
같은 집합이면 그 순서를 쓴다. 아니면 id 순이고, 이때는 태그 순서를 알 수 없다.

**계급:** 캐릭터마다 그 판에 **들어갈 때의** 계급을 남긴다. save-admin 피드는 플레이한 캐릭터의 계급을 싣고,
`save_states.chars`가 `[승, 패, 계급]`으로 그것을 기억한다. 직전 상태에 그 캐릭터 계급이 있으면 그것, 없으면
판이 끝난 세이브의 계급이다. 뒤쪽은 그 캐릭터의 첫 판과, 계급을 기억하기 전에 저장된 상태다. 그 판에서
승급·강등했다면 판 뒤 계급이 찍힌다. 계급은 이벤트(`match_events.ranks`)에 실리고 결과로 복사되므로 재처리해도
남는다. 계급을 기억하기 전에 기록된 판은 `ranks`가 null이다.

## 큐

`match_events`의 상태는 `pending`, `done`, `dead`다.

- 소비자는 `available_at`이 지난 가장 오래된 `pending` 행을 `FOR UPDATE SKIP LOCKED`로 잡는다.
- 상대 조회, 결과 추가, `done` 표시는 한 트랜잭션이다.
- 처리에 실패하면 세이브포인트까지 되돌리고 `attempts`와 `available_at`을 올린다. 재시도 간격은 시도 횟수 × 30초이고,
  5회 실패하면 `dead`다.
- 프로세스가 죽으면 트랜잭션이 롤백되어 `pending`으로 남는다.

## 상대와 양쪽 연결

**상대 조회:** `created_dt <= 저장 시각 <= last_seen_at + 90초`인 방 중 가장 늦게 생긴 방의 상대다. 90초는 마지막 관측이
최대 한 주기 늦고 결과 저장이 방이 사라진 뒤에 올 수 있어서 둔 여유다. `room_id`는 RPCN 재시작으로 재사용되므로
`last_seen_at` 갱신은 같은 두 사람의 하루 이내 행만 건드린다.

**양쪽 연결:** 한 판은 두 사람의 행으로 저장되고 서로 `counterpart_id`로 잇는다. 상대 캐릭터는 이 연결로 읽는다.

| 연결 조건 | 이유 |
|---|---|
| 같은 방, 상대의 행, 반대 결과 | 같은 판의 상대 기록만 고른다 |
| 시각 차 60초 이내 | 한 방에 여러 판이 있어 방만으로는 다른 판과 섞인다 |
| 아직 연결되지 않은 행 | 후보가 여럿이면 가장 가까운 행 |

60초는 임시값이고 측정으로 조정한다. 결과를 넣기 전에 `pg_advisory_xact_lock(room_snapshot_id)`를 잡는다. 소비자가
둘이어도 서로의 미커밋 행을 못 봐서 미확인으로 남는 일이 없게 하기 위해서다.

| 경우 | 기록 |
|---|---|
| 상대 세이브까지 확인 | 양쪽 행이 연결됨 |
| 방은 있으나 상대 세이브가 없음 (이탈 등) | 내 행에 상대가 있고 `counterpart_id`는 비어 있음. 상대 캐릭터는 알 수 없고 상대 전적에는 패배가 없음 |
| 방을 찾지 못함 | `opponent_npid`가 비어 있음 |

## 조회

`GET /records/matches?npid=&q=&before=&limit=`, 공개. 최신순으로 **한 판에 한 줄**이다. 양쪽 행이 연결된 판은
id가 작은 행이 대표한다.

```
{ matches: [{ id, played_at,
              p1: { npid, online_name, result: win | loss, chars: [{ name, rank: { name, tier } | null }] | null },
              p2: (같은 모양) | null }],
  next_before: id | null }
```

**1P/2P:** 그 판 방 스냅샷의 `user1`이 1P다. RPCN은 방 멤버를 슬롯 순서로 내보내고(`member_id`는 슬롯이
상위 비트), 수집기는 그 순서 그대로 `user1`/`user2`에 쓴다. 방을 못 찾은 판은 세이브가 보인 쪽이 1P, `p2`는
null이다. 규칙은 `records.domain.seat`.

| 쿼리 | 의미 |
|---|---|
| `npid` | 그 플레이어가 승자나 패자인 판. 상대 세이브로만 기록된 판도 들어간다 |
| `q` (1~32자) | 두 사람의 npid나 방 이름에 들어 있는 판. `%`, `_`는 글자 그대로 |
| `before`, `limit` (기본 20, 최대 100) | 번호 대신 id로 넘긴다. 판이 계속 들어와도 다음 페이지가 밀리지 않는다 |

- `online_name`은 그 판의 방 스냅샷에서 읽는다. 방이 없으면 null이고 FE는 npid를 보여준다.
- 한쪽 `chars`가 null이면 그 사람의 세이브를 못 본 판이고, `p2`가 null이면 방을 못 찾은 판이다.
- 플레이어별 승패 합계는 내지 않는다. 통산 전적은 세이브(`GET /saves/players/{npid}`)에 있다.
- 캐시는 없다. 판이 10초마다 들어오고 FE는 화면을 열 때와 새로고침 때만 부른다.

## 재처리

상대 매칭 규칙을 바꾼 뒤에는 SQL로 다시 돌린다. 소비자가 그대로 처리한다.

```sql
DELETE FROM match_results;
UPDATE match_events SET status = 'pending', attempts = 0, last_error = NULL, available_at = now();
```

세이브 원본은 저장하지 않으므로, 세이브 해석을 바꿔 과거 전적을 다시 계산할 수는 없다.

## 측정

수집이 맞는지 다음으로 잰다. 기준은 제안값이다. 2026-11-03에 운영 하루치(1,615행)가 모두 기준 안이어서 조회
API와 화면을 만들었다. 60초 연결 창은 그대로 둔다(양쪽 저장 시각 차 최대 12초).

| 지표 | 기준 |
|---|---|
| 승/패 비율 | 0.95~1.05 |
| 상대 특정률 | 95% 이상 |
| 양쪽 확인률 (상대 캐릭터 확보율) | 90% 이상 |
| 같은 판을 둘 다 승 또는 둘 다 패로 기록 | 거의 0 |
| `chars`가 빈 행 | 거의 0 |
| 양쪽 세이브 시각 차 분포 | 60초가 적절한지 판단 |
| `merged_count`, `dead` 건수 | 원인을 설명할 수 있을 것 |

```sql
-- 승/패 수, 상대 특정률, 양쪽 확인률
SELECT result,
       count(*) AS games,
       round(avg((opponent_npid IS NOT NULL)::int), 3) AS resolved,
       round(avg((counterpart_id IS NOT NULL)::int), 3) AS confirmed
FROM match_results GROUP BY result;

-- 연결된 판의 양쪽 저장 시각 차
SELECT percentile_cont(ARRAY[0.5, 0.9, 0.99]) WITHIN GROUP (
         ORDER BY abs(extract(epoch FROM a.played_at - b.played_at)))
FROM match_results a JOIN match_results b ON a.counterpart_id = b.id;

-- 같은 방에서 시각이 가까운데 결과가 같은 행
SELECT count(*) FROM match_results a JOIN match_results b
  ON a.room_snapshot_id = b.room_snapshot_id AND a.npid < b.npid AND a.result = b.result
 AND abs(extract(epoch FROM a.played_at - b.played_at)) <= 60;
```

## 하지 않는 것

세이브 원본 보관, 비랭크 매치, RPCN 수정, 플레이어별 승패 합계.

기존 대전 수 통계(주간 top, 자주 만난 상대)는 `rank_match_snapshots` 기준이라 방 재사용 때문에 실제 판수보다 적다.
이 문서의 전적이 검증되면 옮기는 것을 따로 검토한다.
