#
# Copyright (C) amaGama contributors.
#
# This file is part of amaGama. It is distributed under the GPL3 or
# later license. See the LICENSE file for a copy of the license and
# the AUTHORS.md file for copyright and authorship information.


"""API v2 looks up an abstract: each placeable reduced to a marker (#3603)."""

import pytest

from amagama.abstraction import ABSTRACTION_VERSION, abstract
from amagama.application import amagama_server_factory
from amagama.tests.test_provenance import client, load, query, run  # noqa: F401 - load is a fixture


def v2(c, source, av=ABSTRACTION_VERSION, lang='af', **options):
    return c.get('/api/v2/en/%s/unit/' % lang,
                 query_string=dict(q=abstract(source)[0], av=av, **options))


def v1(c, source):
    response = c.get('/api/v1/en/af/unit/', query_string={'source': source})
    assert response.status_code == 200
    return response.get_json()


@pytest.fixture
def stored(load):  # noqa: F811 - fixture
    run('initdb', '-s', 'en')
    load('gnome-51', 'af', [
        ('Delete {0} files', 'Skrap {0} lêers'),
        ('<b>Open</b> the file', '<b>Maak</b> die lêer oop'),
        ('Save file', 'Stoor lêer'),
    ])


def test_match_differing_in_placeables(stored):
    with client() as c:
        response = v2(c, 'Delete %(count)s files')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'max-age=3600, public'
    assert response.get_json() == {'abstraction': ABSTRACTION_VERSION, 'matches': [{
        'source': 'Delete {0} files', 'target': 'Skrap {0} lêers',
        'quality': 100, 'sources': ['gnome-51']}]}


def test_quality_on_abstracts(stored):
    with client() as c:
        [match] = v2(c, '<strong>Open</strong> the files').get_json()['matches']
    assert match['source'] == '<b>Open</b> the file'
    assert 90 <= match['quality'] < 100


def test_options(stored):
    with client() as c:
        assert v2(c, 'Delete %s files', exclude='gnome-*').get_json()['matches'] == []
        assert v2(c, 'Save', min_similarity=95).get_json()['matches'] == []


def test_v1_scores_raw(stored):
    with client() as c:
        assert v1(c, 'Delete %(count)s files') == []
        [match] = v1(c, 'Delete {0} files')
    assert set(match) == {'source', 'target', 'quality', 'rank', 'sources'}


@pytest.mark.parametrize('av', [ABSTRACTION_VERSION + 1, 0])
def test_other_version(stored, av):
    with client() as c:
        response = v2(c, 'Save file', av=av)
    assert response.status_code == 409
    assert response.get_json() == {'abstraction': ABSTRACTION_VERSION}


def test_version_one(stored):
    """A client with version 1's abstracts is refused, so it uses v1."""
    assert ABSTRACTION_VERSION == 2
    with client() as c:
        response = v2(c, 'Save file', av=1)
    assert response.status_code == 409
    assert response.get_json() == {'abstraction': 2}


@pytest.mark.parametrize('query, source, target', [
    ('{{n}} files', '{{count}} files', '{{count}} lêers'),
    ('Hello { $name }', 'Hello { $user }', 'Hallo { $user }'),
    ('Open %2$@', 'Open %1$@', 'Maak %1$@ oop'),
    ('Value {1:N2}', 'Value {0:N2}', 'Waarde {0:N2}'),
])
def test_format_placeholders(load, query, source, target):  # noqa: F811 - fixture
    """Stored sources of any format are abstracted with every parser, as
    Virtaal abstracts its query."""
    run('initdb', '-s', 'en')
    load('gnome-51', 'af', [(source, target), ('Save file', 'Stoor lêer')])
    with client() as c:
        response = v2(c, query)
    assert response.status_code == 200
    assert response.get_json()['matches'] == [{
        'source': source, 'target': target, 'quality': 100, 'sources': ['gnome-51']}]


def test_schema_without_abstracts(stored, pg_connection):
    with pg_connection.cursor() as cursor:
        cursor.execute("DROP TABLE en.abstraction")
    pg_connection.commit()
    with client() as c:
        response = v2(c, 'Save file')
        assert response.status_code == 409
        assert response.get_json() == {'abstraction': None}
        # v1 still answers.
        assert [match['target'] for match in v1(c, 'Save file')] == ['Stoor lêer']


@pytest.mark.parametrize('query_string', [{'av': '1'}, {'q': 'Save'}, {'q': 'Save', 'av': 'x'}])
def test_bad_request(stored, query_string):
    with client() as c:
        assert c.get('/api/v2/en/af/unit/', query_string=query_string).status_code == 400


def test_unknown_language(stored):
    with client() as c:
        assert v2(c, 'Save file', lang='af').status_code == 200
        assert c.get('/api/v2/xx/af/unit/', query_string={'q': 'Save', 'av': 1}).status_code == 404


def test_swap_in_abstracts(stored, load, pg_connection):  # noqa: F811 - fixture
    """One app serves v2 from a rebuild swapped in under it."""
    with pg_connection.cursor() as cursor:
        cursor.execute("DROP TABLE en.abstraction")
    pg_connection.commit()
    run('initdb', '-s', 'en', '--build')
    load('gnome-51', 'af', [('Delete {0} files', 'Skrap {0} lêers')], '--build')
    app = amagama_server_factory()
    app.testing = True
    with app.test_client() as c:
        assert v2(c, 'Delete %(count)s files').status_code == 409
        assert v1(c, 'Delete {0} files')
        with app.app_context():
            app.tmdb.swap('en')
        response = v2(c, 'Delete %(count)s files')
        assert response.status_code == 200
        assert [match['target'] for match in response.get_json()['matches']] == [
            'Skrap {0} lêers']
        assert v1(c, 'Delete {0} files')
    assert query(pg_connection, "SELECT version FROM en.abstraction") == [(ABSTRACTION_VERSION,)]
