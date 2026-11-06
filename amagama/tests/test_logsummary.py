#
# Copyright (C) amaGama contributors.
#
# This file is part of amaGama. It is distributed under the GPL3 or
# later license. See the LICENSE file for a copy of the license and
# the AUTHORS.md file for copyright and authorship information.


"""Daily counts from the nginx access logs, without IPs or text."""

import datetime
import gzip
import json
from collections import Counter

import pytest
from click.testing import CliRunner

from amagama import logsummary
from amagama.cli import manage
from amagama.logsummary import agent_family, classify, summarise

VIRTAAL = "Virtaal/1.0.0 (Ubuntu 24.04) Build/source"
FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"


def line(when, request, status=200, size=100, agent=VIRTAAL, addr="192.0.2.1"):
    """A log line in nginx's combined format; when is "DD HH:MM:SS" in Nov 2026."""
    day, time = when.split(" ")
    return '%s - - [%s/Nov/2026:%s +0000] "%s" %d %s "-" "%s"\n' % (
        addr, day, time, request, status, size, agent)


def get(path):
    return "GET %s HTTP/1.1" % path


def write(path, lines, compress=False):
    text = "".join(lines)
    if compress:
        with gzip.open(path, "wt", encoding="latin-1") as f:
            f.write(text)
    else:
        path.write_text(text, encoding="latin-1")
    return str(path)


def day(n):
    return datetime.date(2026, 11, n)


@pytest.mark.parametrize("agent, family", [
    (VIRTAAL, "Virtaal 1.0"),
    ("Virtaal/0.7.1 (Windows XP)", "Virtaal 0.7"),
    ("Virtaal/1.1.0rc1 (macOS 15) Build/frozen", "Virtaal 1.1"),
    ("Virtaal", "Virtaal"),
    ("Weblate/5.14", "Weblate 5.14"),
    (FIREFOX, "Firefox"),
    ("Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/141.0 Safari/537.36", "Chrome"),
    ("Mozilla/5.0 (Windows NT 10.0) Chrome/141.0 Safari/537.36 Edg/141.0", "Edge"),
    ("Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 Version/26.0 Safari/605.1.15", "Safari"),
    ("Mozilla/5.0 (compatible; MSIE 9.0)", "other browser"),
    ("Mozilla/5.0 (compatible; Googlebot/2.1)", "bot"),
    ("curl/8.5.0", "script"),
    ("python-requests/2.32", "script"),
    ("-", "none"),
    ("", "none"),
    ("Pootle/2.9", "other"),
])
def test_agent_family(agent, family):
    assert agent_family(agent) == family


@pytest.mark.parametrize("request_line, expected", [
    (get("/api/v1/en/af/unit/Open%20file"), ("v1-unit", "en:af", 9)),
    (get("/tmserver/en/af/unit/Open%20file"), ("tmserver-unit", "en:af", 9)),
    (get("/api/v1/en/af/unit/?source=Open+file&style=gnome"), ("v1-unit", "en:af", 9)),
    (get("/api/v1/en/pt-BR/unit/l%C3%AAer"), ("v1-unit", "en:pt_br", 4)),
    # nginx escapes a raw byte it logs as \xHH.
    (get("/api/v1/en/af/unit/l\\xC3\\xAAer"), ("v1-unit", "en:af", 4)),
    (get("/api/v2/en/af/unit/?av=1&q=Delete%20%7B0%7D%20files"), ("v2-unit", "en:af", 16)),
    (get("/api/v2/en/af/unit/?av=1"), ("v2-unit", "en:af", 0)),
    (get("/api/v1/en/not%20a%20language/unit/file"), ("v1-unit", "invalid", 4)),
    (get("/api/v1/languages/"), ("languages", None, None)),
    (get("/tmserver/languages/"), ("languages", None, None)),
    (get("/api/v1/sources/?lang=af"), ("sources", None, None)),
    (get("/"), ("web", None, None)),
    (get("/static/css/amagama.css"), ("web", None, None)),
    (get("/favicon.ico"), ("web", None, None)),
    (get("/wp-login.php"), ("other", None, None)),
    (get("/api/v1/en/af/store/x"), ("other", None, None)),
    ("OPTIONS /api/v1/en/af/unit/file HTTP/1.1", ("preflight", None, None)),
    ("\\x16\\x03\\x01", ("invalid", None, None)),
])
def test_classify(request_line, expected):
    assert classify(request_line) == expected


def test_length_buckets():
    assert [logsummary.length_bucket(n) for n in (0, 1, 10, 11, 100, 500, 501, 9000)] == [
        "0", "1-10", "1-10", "11-25", "51-100", "251-500", "501+", "501+"]


def test_a_day(tmp_path):
    log = write(tmp_path / "access.log", [
        line("04 23:00:00", get("/")),
        line("05 00:10:00", get("/api/v1/en/af/unit/Open%20file"), size=2),
        line("05 01:00:00", get("/api/v1/en/af/unit/Save%20file"), size=80),
        line("05 01:30:00", get("/api/v1/en/af/unit/Save%20file"), status=304, size=0),
        line("05 02:00:00", get("/api/v2/en/af/unit/?av=1&q=Save%20file"),
             size=len('{"abstraction": 1, "matches": []}')),
        line("05 02:00:00", get("/api/v2/en/af/unit/?av=1&q=Save%20file"), size=120,
             agent=FIREFOX, addr="2001:db8::1"),
        line("05 03:00:00", get("/api/v1/en/zu/unit/x"), size=2, addr="192.0.2.2"),
        line("05 04:00:00", get("/api/v1/en/xh/unit/x"), agent=VIRTAAL + " Test/instance"),
        line("05 04:00:00", get("/api/v1/en/xh/unit/x"), agent=VIRTAAL + " CI/github-actions"),
        "not a log line\n",
        line("06 12:00:00", get("/")),
    ])
    stats = Counter()
    [summary] = summarise([log], until=day(5), stats=stats)
    assert stats == {"unparsed": 1}
    assert summary["day"] == "2026-11-05"
    assert summary["requests"] == 6
    assert summary["hours"][:5] == [1, 2, 2, 1, 0]
    assert summary["endpoints"] == {"v1-unit": 4, "v2-unit": 2}
    assert summary["status"] == {"200": 5, "304": 1}
    assert summary["agents"] == {"Virtaal 1.0": 5, "Firefox": 1}
    assert summary["clients"] == {"distinct": 3, "by_agent": {"Virtaal 1.0": 2, "Firefox": 1}}
    assert summary["pairs"] == {
        "en:af": {"requests": 5, "matched": 2, "empty": 2},
        "en:zu": {"requests": 1, "empty": 1},
    }
    assert summary["results"] == {"v1-unit": {"matched": 1, "empty": 2},
                                  "v2-unit": {"matched": 1, "empty": 1}}
    assert summary["query_length"] == {"v1-unit": {"1-10": 4}, "v2-unit": {"1-10": 2}}
    assert summary["excluded"] == {"test-instance": 1, "ci": 1}


def test_logs_merge_in_time_order(tmp_path):
    """A day split over a rotated, gzipped log and the live one, plus a second
    site's log alongside both."""
    rotated = write(tmp_path / "live.log-20261031.gz", [
        line("01 00:00:01", get("/api/v1/en/af/unit/a")),
        line("01 06:00:00", get("/api/v1/en/af/unit/b")),
    ], compress=True)
    live = write(tmp_path / "live.log", [
        line("01 06:25:00", get("/api/v1/en/af/unit/c")),
        line("02 09:00:00", get("/api/v1/en/af/unit/d")),
    ])
    other = write(tmp_path / "redirect.log", [
        line("01 03:00:00", get("/tmserver/en/af/unit/e")),
        line("02 23:59:59", get("/tmserver/en/af/unit/f")),
    ])
    summaries = list(summarise([live, other, rotated], since=day(1), until=day(2)))
    assert [(s["day"], s["requests"]) for s in summaries] == [
        ("2026-11-01", 4), ("2026-11-02", 2)]
    assert summaries[0]["hours"][:7] == [1, 0, 0, 1, 0, 0, 2]


def test_default_days(tmp_path):
    """The logs' first day may be partial, and so is today."""
    today = datetime.datetime.now(datetime.timezone.utc).date()
    stamp = "%02d/%s/%d" % (today.day, today.strftime("%b"), today.year)
    log = write(tmp_path / "access.log", [
        line("03 12:00:00", get("/")),
        line("04 12:00:00", get("/")),
        line("05 12:00:00", get("/")),
        line("05 12:00:00", get("/")).replace("05/Nov/2026", stamp),
    ])
    assert [s["day"] for s in summarise([log])] == ["2026-11-04", "2026-11-05"]


def test_late_line(tmp_path):
    log = write(tmp_path / "access.log", [
        line("05 12:00:00", get("/")),
        line("06 00:04:00", get("/")),
        line("06 00:06:00", get("/")),
        line("05 23:59:59", get("/")),
        line("06 00:07:00", get("/")),
    ])
    stats = Counter()
    summaries = list(summarise([log], since=day(5), until=day(6), stats=stats))
    assert [(s["day"], s["requests"]) for s in summaries] == [
        ("2026-11-05", 1), ("2026-11-06", 3)]
    assert stats == {"late": 1}


def test_line_shortly_after_midnight(tmp_path):
    """A worker's log line can come a moment after the next day's first."""
    log = write(tmp_path / "access.log", [
        line("06 00:00:01", get("/")),
        line("05 23:59:59", get("/")),
    ])
    summaries = list(summarise([log], since=day(5), until=day(6)))
    assert [(s["day"], s["requests"]) for s in summaries] == [
        ("2026-11-05", 1), ("2026-11-06", 1)]


def test_time_zones(tmp_path):
    log = write(tmp_path / "access.log", [
        line("05 23:30:00", get("/")).replace("+0000", "-0100"),
        line("06 03:30:00", get("/")).replace("+0000", "+0200"),
        line("06 01:30:00", get("/")).replace("+0000", "+0200"),
    ])
    summaries = list(summarise([log], since=day(5), until=day(6)))
    assert [(s["day"], s["requests"]) for s in summaries] == [
        ("2026-11-05", 1), ("2026-11-06", 2)]
    assert summaries[1]["hours"][:2] == [1, 1]


def test_bad_times_are_unparsed(tmp_path):
    log = write(tmp_path / "access.log", [
        line("05 12:00:00", get("/")).replace("Nov", "Foo"),
        line("05 12:00:00", get("/")).replace("12:00:00", "12:00"),
    ])
    stats = Counter()
    assert list(summarise([log], since=day(5), until=day(5), stats=stats)) == []
    assert stats == {"unparsed": 2}


def test_empty_log(tmp_path):
    assert list(summarise([write(tmp_path / "empty.log", [])], until=day(5))) == []


def summarise_logs(*args):
    return CliRunner().invoke(manage, ("summarise_logs",) + args)


@pytest.fixture
def logs(tmp_path):
    return [write(tmp_path / "access.log", [
        line("04 12:00:00", get("/")),
        line("05 12:00:00", get("/api/v1/en/af/unit/Secret%20phrase"), addr="192.0.2.77"),
        line("06 12:00:00", get("/api/v2/en/af/unit/?av=1&q=Hidden%20words"),
             addr="2001:db8::77"),
        line("07 12:00:00", get("/")),
        "garbage\n",
    ])]


def test_command_writes_a_file_a_day(amagama_config, logs, tmp_path):
    output = tmp_path / "summary"
    result = summarise_logs(*logs, "-o", str(output), "--until", "2026-11-06")
    assert result.exit_code == 0, result.output
    assert "Counted 2 days. Left out 1 lines that didn't parse and 0 that came late." in (
        result.output)
    assert sorted(p.name for p in output.iterdir()) == ["2026-11-05.json", "2026-11-06.json"]
    first = (output / "2026-11-05.json").read_text()
    assert json.loads(first)["pairs"] == {"en:af": {"requests": 1, "matched": 1}}

    # Again over the same logs, the files come out the same.
    assert summarise_logs(*logs, "-o", str(output), "--until", "2026-11-06").exit_code == 0
    assert (output / "2026-11-05.json").read_text() == first

    written = "".join(p.read_text() for p in output.iterdir())
    for private in ("192.0.2", "2001:db8", "Secret", "phrase", "Hidden", "words"):
        assert private not in written


def test_command_prints_json_lines(amagama_config, logs):
    result = summarise_logs(*logs, "--since", "2026-11-04", "--until", "2026-11-07")
    assert result.exit_code == 0, result.output
    days = [json.loads(text) for text in result.output.splitlines() if text.startswith("{")]
    assert [d["day"] for d in days] == ["2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07"]
    for private in ("192.0.2", "2001:db8", "Secret", "Hidden"):
        assert private not in result.output
