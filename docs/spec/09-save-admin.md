# 09. 관리자 — TTT2 세이브

## 목적

RPCN 관리자가 사이트에서 플레이어의 TTT2 세이브(TUS, `NPWR02973_00` 슬롯 1)를 조회하고
계급을 고친다. 세이브를 실제로 읽고 쓰는 것은 별도 저장소
[tag2now-save-admin](https://github.com/tag2now/tag2now-save-admin)의 서버다. 이 서버는
권한을 1차로 거르고 요청을 전달할 뿐이다.

## 구조

```
FE ──POST /admin/saves/set-rank {username, password, ...}──▶ tag2now-BE
   Authorization: Bearer <access_token>                        │ 토큰의 admin 클레임 확인 (아니면 403)
                                                               │ POST /saves/set-rank
                                                               │ X-API-Key + {admin_username: 토큰 sub,
                                                               │              admin_password, ...}
                                                               ▼
                                                     save-admin (compose 내부)
                                                               │ RPCN에 관리자 id/pw 재확인
                                                               │ 접속 여부 확인 → 백업 → 쓰기 → 검증 → 감사 로그
FE ◀──{changes, applied, result}──────────────────── tag2now-BE
```

- 08-admin.md와 같이 **호출마다 관리자 비밀번호**를 받고, 변환(`derive_rpcn_password`)해서 넘긴 뒤
  남기지 않는다. 관리자 여부는 save-admin이 RPCN에 다시 묻는다.
- save-admin은 `compose.prod.yml`의 서비스이고 포트를 열지 않는다. `be`만 `http://save-admin:8000`으로 닿는다.
- 설정: `SAVE_ADMIN_URL`(compose가 지정), `SAVE_ADMIN_KEY`(`.env.prod`, save-admin에도 같은 값이 간다),
  `SAVE_ADMIN_TIMEOUT_SECONDS`(기본 20). URL이나 키가 비면 모든 `/admin/saves/*`와 아래의
  `/saves/players/{npid}`가 502다.
- 백엔드 코드는 `saves/` 모듈 하나다. adapter 하나(save-admin 클라이언트 하나)가 관리자 호출과 공개 조회를
  모두 맡고, 라우터가 둘이다(`/admin/saves/*`, `/saves/players/{npid}`). 관리자 확인(`admin_user`)과
  계정 관련 예외만 `admin/`에서 가져다 쓴다.

## 수정은 두 번 호출한다

1. 같은 body에 `dry_run: true`를 넣어 보낸다. 바뀔 내용(`changes`)과 지금 세이브의 `sha256`이 온다.
   아무것도 쓰지 않는다.
2. 같은 body에 `expect_sha256: <1의 sha256>`을 넣어 다시 보낸다. 그 사이 세이브가 바뀌었으면 409로
   거부한다. `expect_sha256` 없이는 쓰지 않는다(400).

바뀌는 것이 없으면 2에서도 쓰지 않고 `applied: false`로 답한다.

**게임에 접속 중인 계정은 고칠 수 없다(409).** 게임이 다음 저장 때 새 세이브로 덮어써서 수정이
사라지기 때문이다. 미리보기 응답의 `online`으로 미리 알 수 있다(RPCN이 답하지 못하면 `null`).

## API

모든 라우트는 관리자 토큰이 필요하고, body에 관리자 자신의 `password`를 싣는다.

| 경로 | body | 응답 |
|------|------|------|
| `/admin/saves/show` | `username`, `all_chars?` | 세이브: 계정 계급·전적, 캐릭터별 계급·점수·연승 |
| `/admin/saves/backups` | `username` | `{backups: [{label, total, account_rank}]}` |
| `/admin/saves/log` | `username?`, `n?`(1–500, 기본 50) | `{records: [{ts, user, action, username, details}]}` |
| `/admin/saves/set-rank` | `username`, `char`(0–58 또는 `"all"`), `rank`(0–42), `points?` | 수정 응답 |
| `/admin/saves/set-account-rank` | `username`, `rank`(0–42) | 수정 응답 |
| `/admin/saves/floor` | `username`, `rank?`(1–42), `fix_points?`, `refloor?` | 수정 응답 + `floor` |
| `/admin/saves/restore` | `username`, `label` | 수정 응답 |

- 모두 `POST`다(비밀번호가 body에 실린다). 수정 라우트 넷은 `dry_run`, `expect_sha256`을 받는다.
- `username`은 대소문자를 구분하지 않는다. 대소문자만 다른 계정이 여럿이면 400이다.
- `char: "all"`은 모든 캐릭터와 계정 계급을 그 계급의 floor 점수, 연승 0으로 맞춘다. `points`와 함께 쓸 수 없다.
- `floor`는 `rank`를 비우면 도달한 최고 계급에서 두 단계 아래를 쓴다. floor 아래 캐릭터가 몇 개뿐이면
  이전 floor 뒤의 강등으로 보고 쓰지 않는다(409). 그래도 올리려면 `refloor: true`.
- 수정 응답: `{username, sha256, online, changes: {account_rank, chars}, applied, result}`.
  `result`는 쓴 경우에만 `{backup, checksum, data_id, landed}`다. `backup`은 쓰기 직전 세이브의
  백업 이름이라 `restore`의 `label`로 그대로 쓸 수 있다. `landed: false`는 쓰는 동안 게임이 저장해서
  수정이 묻힌 경우다.
- 감사 로그의 `user`는 사이트에서 고친 경우 관리자 아이디, 호스트 CLI에서 고친 경우 셸 사용자다.
  사이트 수정은 `details.via`가 `"web"`이다.

| 상황 | 상태 | `detail` |
|------|------|----------|
| 토큰 없음·만료·위조 | 401 | (07-auth.md와 같음) |
| 관리자 아님 (토큰 또는 RPCN 판단) | 403 | 관리자 권한이 없습니다. |
| 관리자 비밀번호 불일치 | **400** | 비밀번호가 올바르지 않습니다. |
| 필드 형식 위반 | 422 | (필드 이름을 담은 문장) |
| 대소문자만 다른 계정 여럿, save-admin이 거부한 값 | 400 | … |
| 계정 없음 / 세이브 없음 / 백업 없음 | 404 | 해당 아이디의 계정이 없습니다. / 이 계정에는 TTT2 세이브가 없습니다. / 해당 백업이 없습니다. |
| 접속 중 / 미리보기 뒤 세이브 변경 / 강등 추정 | 409 | … |
| 접속 여부 확인 불가, RPCN·save-admin 연결 불가, 미설정 | 502 | … |

비밀번호 불일치가 401이 아닌 이유는 08-admin.md와 같다.

## 플레이어 프로필의 세이브 계급 (공개, 읽기 전용)

`GET /saves/players/{npid}` — 로그인 없이 누구나 어떤 플레이어든 조회한다. 프로필 패널이 쓴다.
계급은 리더보드에도 나오는 정보라 기록 API(`/history/players/{npid}`)처럼 공개다.

| 필드 | 설명 |
|------|------|
| `username` | RPCN 아이디(실제 대소문자) |
| `saved_at` | 게임이 세이브를 마지막으로 쓴 시각(UTC) |
| `account_rank` | 계정 계급 코드 |
| `total`, `wins`, `losses` | 계정 전적 |
| `chars[]` | 쓴 적 있는 캐릭터의 `id, character, rank, rank_name, tier, points, streak, wins, losses` |

- save-admin의 `GET /player/save`를 부른다. 관리자 확인 없이 API 키만 쓰는 유일한
  경로이고, 파일 위치·sha256·체크섬·접속 여부는 save-admin이 애초에 내보내지 않는다.
- **캐시 10분**(`cache_ttl_player_save`, 키 `saves:player:{소문자 npid}`). 게임은 세션이 끝날 때
  세이브를 쓰고, 계급이 몇 분 늦게 보여도 문제가 없다. 세이브 없음도 캐시한다. 연결 실패는 캐시하지 않는다.
- 관리자 수정이 실제로 쓰였으면(`applied`) 그 플레이어의 캐시를 바로 지운다. 미리보기는 지우지 않는다.

| 상황 | 상태 | detail |
|------|------|--------|
| 계정 없음 / 세이브 없음 | 404 | 이 플레이어의 TTT2 세이브가 없습니다. |
| save-admin 연결 불가, 미설정 | 502 | 세이브 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요. |

## 사이트에서 하지 않는 것

전체 계정 floor, floor 재실행(`--redo`), 접속 중 강제 쓰기(`--force`), 고아 세이브 정리(`gc`),
파일을 지정한 적용은 호스트의 `tdt_admin.py`로만 한다.
