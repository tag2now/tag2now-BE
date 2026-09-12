# 05. 커뮤니티 게시판

## 식별 — 인증이 아니다

로그인이 없다. 사용자는 닉네임만 정한다.

1. FE가 `POST /community/identity`로 닉네임을 등록한다 → 서버가 `community_user` 쿠키(HttpOnly, SameSite=Lax) 설정.
2. 이후 쓰기 요청에서 서버는 `X-Community-User` 헤더 또는 `community_user` 쿠키를 읽는다(최대 50자로 잘림).
3. 값이 없으면 **400**.

**검증은 전혀 없다.** 다른 사람 닉네임을 그대로 보내면 그 사람으로 글을 쓰고 지울 수 있다.
현재 신뢰 모델은 "소규모 커뮤니티의 선의"이며, 계정 체계가 들어오기 전까지의 임시 구조다.

FE는 `useIdentity().ensureIdentity()`로 세션당 1회만 등록하고(`useRef` 가드),
모든 쓰기 전에 `await ensureIdentity()`를 호출한다. 닉네임이 없으면 한국어 에러를 던진다.
`fetch`는 쿠키 전송을 위해 항상 `credentials: 'include'`다.

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
