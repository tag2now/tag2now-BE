# 08. 관리자 — 계정 밴

## 목적

RPCN 관리자 계정으로 로그인한 사람이 사이트에서 RPCN 계정을 조회하고 밴한다.
밴은 **RPCN의 밴**이다. 이 서버는 따로 밴 목록을 두지 않는다.

## 구조 — 판단은 rpcn-narco가 한다

```
FE ──POST /admin/users/ban {username, password}──▶ tag2now-BE
   Authorization: Bearer <access_token>             │ 토큰의 admin 클레임 확인 (아니면 403)
                                                    │ POST /admin/users/ban
                                                    │ X-API-Key + {admin_username: 토큰 sub,
                                                    │              admin_password, username}
                                                    ▼
                                             rpcn-narco API server
                                                    │ 관리자 id/pw 재확인 → banned = TRUE,
                                                    │ 접속 중이면 연결 종료
FE ◀──{username, banned, kicked}──────────── tag2now-BE
```

- rpcn-narco의 관리 API는 **호출마다 관리자 비밀번호**를 요구한다. 이 서버는 비밀번호를
  저장하지 않으므로(07-auth.md) 관리자가 조회·밴할 때마다 자기 비밀번호를 다시 입력한다.
  비밀번호는 로그인과 같은 방식(`derive_rpcn_password`)으로 변환해 전달하고, 어디에도 남기지 않는다.
- 토큰의 `admin` 클레임은 1차 필터일 뿐이다. 토큰은 최대 7일 묵을 수 있으므로, 그 사이
  관리자 권한을 잃었거나 밴된 관리자는 rpcn-narco가 403으로 막는다.
- rpcn-narco 설정(`RPCN_API_SERVER_URL`, `RPCN_API_SERVER_KEY`, 타임아웃)은 로그인과 공유한다.

## 밴의 효과

| 대상 | 효과 |
|------|------|
| RPCS3 접속 | 접속 중이면 즉시 끊기고(`kicked: true`), 다시 로그인할 수 없다 |
| 이 사이트 로그인 | 403 "이용이 제한된 계정입니다." |
| 이 사이트의 기존 토큰 | **만료될 때까지(최대 7일) 유효하다.** 게시판·예약 쓰기가 계속 가능하다 |

기존 토큰을 즉시 막지 않는 것은 의도된 선택이다. 막으려면 이 서버가 밴 목록을 따로 두고
인증마다 확인해야 하는데, rpcn-narco나 vpn-monitor에서 직접 한 밴은 그 목록에 들어오지 않는다.

**밴 해제는 없다.** rpcn-narco에 해제 API가 없으므로 해제는 RPCN DB를 직접 고친다.

## API

두 라우트 모두 관리자 토큰이 필요하다. 비밀번호가 body에 실리므로 조회도 `POST`다.

| 메서드 | 경로 | body | 응답 |
|--------|------|------|------|
| POST | `/admin/users/lookup` | `{username, password}` | `{username, online_name, avatar_url, admin, banned, online, created_at, last_login_at}` |
| POST | `/admin/users/ban` | `{username, password}` | `{username, banned: true, kicked}` |

- `username`은 대상 계정, `password`는 **관리자 자신의** 비밀번호다.
- rpcn-narco는 `username`을 **대소문자까지 정확히** 비교한다. 리더보드의 ID(`np_id`) 표기를 그대로 쓴다.
- `created_at`, `last_login_at`은 UTC ISO 8601이다. 타임스탬프 테이블 이전에 만든 계정이거나
  한 번도 로그인하지 않았으면 `null`이다.
- `kicked`는 밴 시점에 RPCS3로 접속 중이어서 연결을 끊었는지 여부다.

| 상황 | 상태 | `detail` |
|------|------|----------|
| 토큰 없음·만료·위조 | 401 | (07-auth.md와 같음) |
| 토큰의 사용자가 관리자가 아님 | 403 | 관리자 권한이 없습니다. |
| rpcn-narco가 관리자로 인정하지 않음 | 403 | 관리자 권한이 없습니다. |
| 관리자 비밀번호 불일치 | **400** | 비밀번호가 올바르지 않습니다. |
| 자기 계정 밴 (대소문자 무시) | 400 | 자기 계정은 밴할 수 없습니다. |
| 대상 계정 없음 | 404 | 해당 아이디의 계정이 없습니다. 대소문자까지 정확히 입력해 주세요. |
| rpcn-narco 연결 불가·API 꺼짐·미설정 | 502 | RPCN 관리 서버에 연결할 수 없습니다. … / 관리 기능이 설정되지 않았습니다. |

비밀번호 불일치가 401이 아닌 이유: FE는 토큰을 실은 요청이 401을 받으면 세션을 끝낸다
(`shared/util/api.ts`). 토큰은 멀쩡한데 재입력한 비밀번호를 틀렸다고 로그아웃되면 안 된다.

rpcn-narco는 관리자가 아닌 호출자와 틀린 API 키에 같은 403을 준다. 같은 키로 로그인이
되고 있다면 앞쪽이므로 403으로 보이고, 서버 로그에는 두 가능성을 모두 남긴다.

## 기록

관리 행위는 rpcn-narco 로그에 `Admin <관리자> banned user <대상> via API server`로 남는다.
이 서버는 따로 기록하지 않는다.
