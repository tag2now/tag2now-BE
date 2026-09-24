# 05. 커뮤니티 게시판

## 식별 — RPCN 계정

쓰기(글 작성·수정·삭제, 댓글, 추천)는 로그인이 필요하다([07-auth.md](07-auth.md)). 조회는 로그인 없이 된다.

- 서버는 `Authorization: Bearer` 토큰의 **RPCN `username`** 을 작성자(`author`)와 추천자(`voter`)로 쓴다.
  게시판은 이름 하나로 표시와 소유권을 겸하므로, 바꿀 수 있는 `online_name`이 아니라 고유한 `username`을 쓴다.
- 토큰이 없거나 잘못되면 **401**. 예전의 `X-Community-User` 헤더, `community_user` 쿠키,
  `POST /community/identity`는 삭제되었다.

**로그인 이전 글**: 예전 글의 `author`는 자유 입력 닉네임이다. 그 닉네임이 어떤 RPCN `username`과
우연히 같으면 그 계정이 해당 글의 소유자가 된다. 같지 않은 글은 아무도 수정·삭제할 수 없다.

## 게시글

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/community/posts?page&page_size&post_type&characters` | 목록 (page ≥ 1, page_size 1~100 기본 20) |
| POST | `/community/posts` | 작성 (201) |
| GET | `/community/posts/{id}` | 상세 + 댓글 트리 |
| PATCH | `/community/posts/{id}` | 수정 — 작성자 본인만, 편집 가능한 필드 전부를 보낸다 |
| DELETE | `/community/posts/{id}` | 작성자 본인만 (204) |

### 글 종류(`post_type`)

`자유`, `건의`, `공략` 중 하나. 기본값 `자유`. 캐릭터는 여기에 넣지 않는다 — 아래 `characters`.

### 캐릭터 태그(`characters`)

TTT2는 2인 태그 팀으로 싸우므로 글 하나에 **캐릭터를 최대 2개**(`TTT2_CHARACTERS` 이름) 붙인다.
중복 불가, 순서는 작성자가 고른 대로 보존한다. 비워 두면 캐릭터 무관 글이다.

- 목록 필터는 `characters`를 반복해서 보낸다(`?characters=Jin&characters=Kazuya`, 최대 2개).
  **선택한 캐릭터를 모두 포함한 글**만 남는다 — 1개면 그 캐릭터가 들어간 모든 글, 2개면 그 팀.
  순서는 무관하며 `post_type` 필터와 함께 쓸 수 있다.
- PostgreSQL은 `text[]` 컬럼 + GIN 인덱스로 `characters @> ARRAY[...]`를 처리한다.
- 예전에는 `post_type`에 캐릭터 이름을 넣었다. 마이그레이션 `e7b3f5a2c914`가 그런 글을
  `post_type='공략'`, `characters=[캐릭터]`로 옮겼다.

### 제약

`title` 1~100자, `body` 1~1000자, `characters` 0~2개.

## 댓글

`POST /community/posts/{post_id}/comments` — `body`(1~1000자), `parent_id`(선택).

- 저장은 평면 구조이고, **트리는 조회 시점에 라우터가 조립한다**: `parent_id`가 부모의 `replies`에 붙고,
  부모가 없거나 목록에 없으면 최상위로 승격된다(고아 댓글이 사라지지 않는다).
- 상세 조회는 글과 댓글을 `asyncio.gather`로 동시에 읽는다.

## 추천 (게시글 한정)

`POST /community/posts/{post_id}/thumb` — `{"direction": "up" | "down"}`.
서버 내부에서는 `+1 / -1`로 변환된다. 한 사용자는 글당 한 표만 가진다.

| 이전 상태 | 동작 |
|-----------|------|
| 없음 | 해당 방향으로 투표 |
| 같은 방향 | 투표 취소(삭제) |
| 반대 방향 | 방향 전환 |

응답은 재집계된 `{ thumbs_up, thumbs_down }`이다. 집계는 글 행을 `SELECT ... FOR UPDATE`로 잠근 뒤 수행되므로
동시 투표에서도 카운트가 어긋나지 않는다. 댓글에는 추천이 없다.

## 캐싱

- 목록: `community:posts:p{page}:s{size}:t{type}:c{정렬된 캐릭터}`, 상세: `community:post:{id}`. TTL 30초.
- **무효화는 라우터가 소유한다**. 글 작성/삭제 시 `community:posts:*`, 댓글·추천 시 `community:post:{id}`.

## 저장소

`community/db.py`가 `db_type` 설정에 따라 PostgreSQL 또는 DynamoDB 어댑터를 런타임에 고른다(어댑터는 분기 안에서 지연 임포트).
현재 운영은 PostgreSQL이며, `db_type` 설정은 소스에 제거 예정으로 표시되어 있다.

## 화면

- 경로 `/community`, 상세 `/community/:postId`. 상세는 로컬 상태가 아니라 **라우트**라 링크 공유가 된다.
- 글쓰기(`create`)만 URL이 없는 로컬 모드다 — 아직 존재하지 않는 글에는 링크할 대상이 없기 때문.
