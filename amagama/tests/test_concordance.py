#
# Copyright (C) amaGama contributors.
#
# This file is part of amaGama. It is distributed under the GPL3 or
# later license. See the LICENSE file for a copy of the license and
# the AUTHORS.md file for copyright and authorship information.

"""Concordance search: the translations whose English holds a phrase (#3227)."""

import pytest
from click.testing import CliRunner

from amagama import tmdb
from amagama.application import amagama_server_factory
from amagama.cli import manage

LONG = ("When the printer is shared on the network, every computer that can reach this one "
        "may send documents to it, and its queue shows them all")
UNITS = [
    ("Open File", "Maak lêer oop"),
    ("Open &File...", "Maak &lêer oop..."),
    ("Open %s file", "Maak %s-lêer oop"),
    ("Opening files", "Lêers word oopgemaak"),
    ("Save the file", "Stoor die lêer"),
    ("Profile", "Profiel"),
    ("The file", "Die lêer"),
    (LONG, "Wanneer die drukker gedeel word ..."),
]


@pytest.fixture
def deployed(amagama_config, tmp_path):
    """A deployed TM of UNITS into Afrikaans, and the first two into Zulu."""
    runner = CliRunner()
    args = [("initdb", "-s", "en")]
    for lang, units in (("af", UNITS), ("zu", [("Open File", "Vula ifayela")])):
        po = tmp_path / ("%s.po" % lang)
        po.write_text('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n' +
                      "".join('msgid "%s"\nmsgstr "%s"\n\n' % unit for unit in units),
                      encoding="utf-8")
        args.append(("build_tmdb", "-s", "en", "-t", lang, "-i", str(po)))
    for arg in args + [("deploy_db",)]:
        result = runner.invoke(manage, arg, input="y\n")
        assert result.exit_code == 0, result.output


def search(query="", lang="af", status=200, **options):
    app = amagama_server_factory()
    with app.test_client() as client:
        response = client.get("/api/v1/en/%s/concordance" % lang,
                              query_string=dict(options, q=query))
        assert response.status_code == status, response.data
        return response.get_json()


def sources(found):
    return [match["source"] for match in found["matches"]]


def test_part_of_a_word(deployed):
    """Part of a word is found, after whole words and the phrase's own case,
    shorter English first."""
    found = search("file")
    assert sources(found) == ["The file", "Open %s file", "Save the file", "Open File",
                              "Open &File...", "Profile", "Opening files"]
    assert (found["total"], found["complete"]) == (7, True)
    [profile] = [m for m in found["matches"] if m["source"] == "Profile"]
    assert profile["target"] == "Profiel"
    assert (profile["hits"], profile["whole"], profile["exact"]) == (
        {"source": [[3, 7]]}, False, True)
    assert set(profile) >= {"sources", "checks"}


def test_whole_words(deployed):
    found = search("file", whole="1")
    assert sources(found) == ["The file", "Open %s file", "Save the file", "Open File",
                              "Open &File..."]
    assert found["complete"]


def test_past_accelerators_and_placeables(deployed):
    """As Virtaal finds it: "Open File" in "Open &File...", "Open %d file"
    in "Open %s file"."""
    found = search("Open File")
    assert sources(found) == ["Open File", "Open &File..."]
    assert found["matches"][1]["hits"] == {"source": [[0, 10]]}
    assert sources(search("Open %d file", whole="1")) == ["Open %s file"]


def test_case(deployed):
    assert sources(search("File", case="1")) == ["Open File", "Open &File..."]


def test_stop_words(deployed):
    """Whole words that are all stop words aren't in the index: they're
    found by reading the sources. The phrase's own case comes first."""
    assert sources(search("the", whole="1")) == ["Save the file", LONG, "The file"]


def test_long_source(deployed):
    """Each band of lengths is searched."""
    assert sources(search("printer is shared", whole="1")) == [LONG]


def test_language(deployed):
    found = search("file", lang="zu")
    assert [(m["source"], m["target"]) for m in found["matches"]] == [
        ("Open File", "Vula ifayela")]
    assert search("file", lang="xh")["matches"] == []


def test_limit(deployed):
    found = search("file", limit="2")
    assert sources(found) == ["The file", "Open %s file"]
    assert found["total"] == 7
    assert len(search("file", limit="nonsense")["matches"]) == 7


def test_too_short(deployed):
    assert search("a") == {"matches": [], "total": 0, "complete": True}


def test_sides(deployed):
    """Only the English is searched: "both" isn't complete, "target" is
    refused."""
    found = search("file", side="both")
    assert len(found["matches"]) == 7 and not found["complete"]
    search("lêer", side="target", status=400)
    search("file", side="neither", status=400)
    search("nul\x00", status=400)
    search("file", lang="en", status=400)


def test_unknown_source_language(deployed):
    app = amagama_server_factory()
    with app.test_client() as client:
        assert client.get("/api/v1/xx/af/concordance?q=file").status_code == 404


def test_timeout(deployed, monkeypatch):
    """A search reading the sources too long gives what it has (nothing)
    and says it isn't complete; the connection goes on working."""
    monkeypatch.setattr(tmdb, "_STRIP_ACCELERATORS",
                        "(s.text || (SELECT '' FROM PG_SLEEP(0.2)))")
    app = amagama_server_factory()
    app.config["CONCORDANCE_TIMEOUT"] = 50
    with app.test_client() as client:
        response = client.get("/api/v1/en/af/concordance?q=file")
        assert response.status_code == 200
        assert response.get_json() == {"matches": [], "total": 0, "complete": False}
        monkeypatch.undo()
        assert len(client.get("/api/v1/en/af/concordance?q=file").get_json()["matches"]) == 7
        assert client.get("/api/v1/en/af/unit/file").status_code == 200
