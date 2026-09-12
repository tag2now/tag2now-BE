"""Character tags: a post names up to one team, and the list filters by it."""

HEADERS = {'X-Community-User': 'tagger'}


def create(client, title, characters, post_type='공략'):
    response = client.post('/community/posts', headers=HEADERS, json={
        'title': title, 'body': 'body', 'post_type': post_type, 'characters': characters,
    })
    assert response.status_code == 201
    return response.json()


def titles(client, **params):
    query = [(key, value) for key, values in params.items() for value in (values if isinstance(values, list) else [values])]
    data = client.get('/community/posts', params=query).json()
    assert data['total'] == len(data['posts'])
    return {post['title'] for post in data['posts']}


def test_team_survives_create_detail_and_list(client):
    post = create(client, 'team', ['Kazuya', 'Jin'])

    assert post['characters'] == ['Kazuya', 'Jin']
    assert client.get(f"/community/posts/{post['id']}").json()['characters'] == ['Kazuya', 'Jin']
    assert client.get('/community/posts').json()['posts'][0]['characters'] == ['Kazuya', 'Jin']


def test_post_without_characters_lists_an_empty_team(client):
    post = create(client, 'free', [], post_type='자유')

    assert post['characters'] == []


def test_filter_keeps_posts_naming_every_selected_character(client):
    create(client, 'jin-kazuya', ['Jin', 'Kazuya'])
    create(client, 'jin-solo', ['Jin'])
    create(client, 'lars-alisa', ['Lars', 'Alisa'])
    create(client, 'untagged', [])

    assert titles(client, characters='Jin') == {'jin-kazuya', 'jin-solo'}
    assert titles(client, characters=['Kazuya', 'Jin']) == {'jin-kazuya'}
    assert titles(client, characters=['Jin', 'Lars']) == set()


def test_filter_combines_with_post_type(client):
    create(client, 'jin-guide', ['Jin'], post_type='공략')
    create(client, 'jin-chat', ['Jin'], post_type='자유')

    assert titles(client, characters='Jin', post_type='자유') == {'jin-chat'}


def test_edit_moves_the_post_between_character_filters(client):
    post = create(client, 'retag', ['Jin'])
    assert titles(client, characters='Jin') == {'retag'}

    response = client.patch(f"/community/posts/{post['id']}", headers=HEADERS, json={
        'title': 'retag', 'body': 'body', 'post_type': '공략', 'characters': ['Lars', 'Alisa'], 'youtube_video_id': None,
    })

    assert response.status_code == 200
    assert response.json()['characters'] == ['Lars', 'Alisa']
    assert titles(client, characters='Jin') == set()
    assert titles(client, characters=['Alisa', 'Lars']) == {'retag'}
