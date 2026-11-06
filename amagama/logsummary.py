#
# Copyright (C) amaGama contributors.
#
# This file is part of amaGama. It is distributed under the GPL3 or
# later license. See the LICENSE file for a copy of the license and
# the AUTHORS.md file for copyright and authorship information.


"""Daily counts from nginx access logs, without IP addresses or looked-up text.

Each log line is reduced to counters at once: the client address only feeds
a hash keyed with a salt made for that day and dropped once the day is
counted, and a query only gives its length.
"""

import calendar
import datetime
import gzip
import hashlib
import heapq
import itertools
import json
import os
import re
from collections import Counter, defaultdict
from urllib.parse import unquote_to_bytes, urlsplit

from amagama.tmdb import lang_to_table

# The "combined" format.
LINE = re.compile(r'(?P<addr>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "(?P<request>[^"]*)" '
                  r'(?P<status>\d{3}) (?P<bytes>\d+|-) "[^"]*" "(?P<agent>[^"]*)"')
TIME = re.compile(r'(\d\d)/(\w{3})/(\d{4}):(\d\d):(\d\d):(\d\d) ([+-])(\d\d)(\d\d)$')
MONTHS = {name: number for number, name in enumerate(calendar.month_abbr) if name}
# nginx writes a byte it escapes as \xHH.
ESCAPE = re.compile(rb'\\x([0-9A-Fa-f]{2})')

# A line written up to this long after midnight may still belong to the day before.
GRACE = 300

LENGTHS = ((0, "0"), (10, "1-10"), (25, "11-25"), (50, "26-50"), (100, "51-100"),
           (250, "101-250"), (500, "251-500"))

BROWSERS = (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
            ("Chrome/", "Chrome"), ("Safari/", "Safari"))
SCRIPTS = ("curl/", "Wget/", "python", "Python", "Go-http-client", "okhttp", "Java/",
           "libwww-perl", "node-fetch", "axios")
BOT = re.compile(r'bot|crawl|spider|slurp', re.IGNORECASE)
VERSIONED = re.compile(r'(Virtaal|Weblate)/(\d+)\.(\d+)')

UNIT_ENDPOINTS = {"tmserver": "tmserver-unit", "api/v1": "v1-unit", "api/v2": "v2-unit"}
# The JSON of a v2 reply with no matches is shorter than this; one with a
# match is longer.
V2_EMPTY_BELOW = 40


def agent_family(agent):
    """The client's family, and for Virtaal and Weblate its x.y version."""
    match = VERSIONED.match(agent)
    if match:
        return "%s %s.%s" % match.groups()
    if agent.startswith(("Virtaal", "Weblate")):
        return agent.split("/", 1)[0].split(" ", 1)[0]
    if not agent or agent == "-":
        return "none"
    if BOT.search(agent):
        return "bot"
    if agent.startswith("Mozilla/"):
        for marker, name in BROWSERS:
            if marker in agent:
                return name
        return "other browser"
    if agent.startswith(SCRIPTS):
        return "script"
    return "other"


def excluded(agent):
    """The traffic agent is kept apart as, or None."""
    if agent.endswith(" Test/instance"):
        return "test-instance"
    if agent.startswith("Virtaal") and " CI/" in agent:
        return "ci"
    return None


def length_bucket(length):
    for limit, name in LENGTHS:
        if length <= limit:
            return name
    return "501+"


def _text(raw):
    """Characters in a logged, percent-encoded piece of a request."""
    raw = ESCAPE.sub(lambda m: bytes([int(m.group(1), 16)]), raw.encode("latin-1"))
    return unquote_to_bytes(raw).decode("utf-8", "replace")


def _argument(query, name):
    """The raw value of a query string's first argument called name."""
    for argument in query.split("&"):
        key, _, value = argument.partition("=")
        if key == name:
            return value
    return ""


def classify(request):
    """(endpoint, language pair, query length, v2) for a logged request line.

    The pair and length are None when the request isn't a unit lookup.
    """
    parts = request.split(" ")
    if len(parts) != 3 or not parts[2].startswith("HTTP/"):
        return "invalid", None, None
    method, target = parts[0], parts[1]
    if method == "OPTIONS":
        return "preflight", None, None
    url = urlsplit(target)
    path = url.path.lstrip("/")
    if path in ("", "favicon.ico") or path.startswith("static/"):
        return "web", None, None
    for prefix, endpoint in UNIT_ENDPOINTS.items():
        if not path.startswith(prefix + "/"):
            continue
        rest = path[len(prefix) + 1:].split("/", 3)
        if rest[0] in ("languages", "sources") and len(rest) <= 2:
            return rest[0], None, None
        if len(rest) < 3 or rest[2] != "unit":
            return "other", None, None
        slang, tlang = lang_to_table(_text(rest[0])), lang_to_table(_text(rest[1]))
        pair = "%s:%s" % (slang, tlang) if slang and tlang else "invalid"
        if endpoint == "v2-unit":
            text = _argument(url.query, "q")
        elif len(rest) == 4 and rest[3]:
            text = rest[3]
        else:
            text = _argument(url.query, "source")
        return endpoint, pair, len(_text(text))
    return "other", None, None


class Day:
    """The counts for one day; its salt goes when it does."""

    def __init__(self, day):
        self.day = day
        self._salt = os.urandom(16)
        self._clients = set()
        self.requests = 0
        self.hours = [0] * 24
        self.endpoints = Counter()
        self.status = Counter()
        self.agents = Counter()
        self.pairs = defaultdict(Counter)
        self.results = defaultdict(Counter)
        self.lengths = defaultdict(Counter)
        self.excluded = Counter()

    def add(self, hour, addr, status, size, agent, request):
        kept_apart = excluded(agent)
        if kept_apart:
            self.excluded[kept_apart] += 1
            return
        family = agent_family(agent)
        self._clients.add((family, hashlib.blake2b(addr.encode(), key=self._salt,
                                                   digest_size=8).digest()))
        self.requests += 1
        self.hours[hour] += 1
        self.status[status] += 1
        self.agents[family] += 1
        endpoint, pair, length = classify(request)
        self.endpoints[endpoint] += 1
        if pair is None:
            return
        self.pairs[pair]["requests"] += 1
        self.lengths[endpoint][length_bucket(length)] += 1
        if status == "200" and size != "-":
            empty = int(size) < (V2_EMPTY_BELOW if endpoint == "v2-unit" else 3)
            outcome = "empty" if empty else "matched"
            self.pairs[pair][outcome] += 1
            self.results[endpoint][outcome] += 1

    def summary(self):
        clients = Counter(family for family, _ in self._clients)
        distinct = len({digest for _, digest in self._clients})
        return {
            "day": self.day.isoformat(),
            "requests": self.requests,
            "hours": self.hours,
            "endpoints": dict(self.endpoints),
            "status": dict(self.status),
            "agents": dict(self.agents),
            "clients": {"distinct": distinct, "by_agent": dict(clients)},
            "pairs": {pair: dict(counts) for pair, counts in self.pairs.items()},
            "results": {name: dict(counts) for name, counts in self.results.items()},
            "query_length": {name: dict(counts) for name, counts in self.lengths.items()},
            "excluded": dict(self.excluded),
        }


def parse_time(text):
    """Seconds since the epoch (UTC) for a logged time, or None."""
    match = TIME.match(text)
    if not match:
        return None
    day, month, year, hour, minute, second, sign, off_h, off_m = match.groups()
    if month not in MONTHS:
        return None
    local = calendar.timegm((int(year), MONTHS[month], int(day), int(hour), int(minute),
                             int(second)))
    offset = (int(off_h) * 60 + int(off_m)) * 60
    return local - offset if sign == "+" else local + offset


def open_log(path):
    with open(path, "rb") as f:
        compressed = f.read(2) == b"\x1f\x8b"
    if compressed:
        return gzip.open(path, "rt", encoding="latin-1", newline="\n")
    return open(path, "rt", encoding="latin-1", newline="\n")


class Log:
    """A log's parsed lines, (seconds, fields), oldest first."""

    def __init__(self, path, stats):
        self.path = path
        self.stats = stats

    def lines(self):
        cached_text, cached_time = None, None
        with open_log(self.path) as f:
            for line in f:
                match = LINE.match(line)
                if not match:
                    self.stats["unparsed"] += 1
                    continue
                text = match.group("time")
                if text != cached_text:
                    cached_text, cached_time = text, parse_time(text)
                if cached_time is None:
                    self.stats["unparsed"] += 1
                    continue
                yield cached_time, match

    def first(self):
        for seconds, _ in self.lines():
            return seconds
        return None


def merged(paths, stats):
    """Every log's lines in time order, with only the logs that overlap open."""
    pending = []
    for path in paths:
        skipped = Counter()
        first = Log(path, skipped).first()
        if first is None:
            # Nothing to read again for: its lines are all unparsed.
            stats.update(skipped)
        else:
            pending.append((first, path))
    pending.sort(key=lambda item: item[0], reverse=True)
    heap = []
    order = itertools.count()

    def advance(lines, number):
        for seconds, match in lines:
            heapq.heappush(heap, (seconds, number, match, lines))
            return

    while pending or heap:
        while pending and (not heap or pending[-1][0] <= heap[0][0]):
            advance(Log(pending.pop()[1], stats).lines(), next(order))
        seconds, number, match, lines = heapq.heappop(heap)
        yield seconds, match
        advance(lines, number)


def summarise(paths, since=None, until=None, stats=None):
    """Yield each day's summary, oldest first, for the days from since to until.

    since defaults to the day after the logs' first, which they may start
    part way through; until to yesterday (UTC). stats counts the lines
    that didn't parse ("unparsed") and came after their day was done ("late").
    """
    stats = Counter() if stats is None else stats
    if until is None:
        until = datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=1)
    days = {}
    done = None

    for seconds, match in merged(paths, stats):
        stamp = datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc)
        day = stamp.date()
        if since is None:
            since = day + datetime.timedelta(days=1)
        if done is not None and day <= done:
            stats["late"] += 1
            continue
        for old in sorted(days):
            if seconds - calendar.timegm(old.timetuple()) > 86400 + GRACE:
                done = old
                yield days.pop(old).summary()
        if not since <= day <= until:
            continue
        if day not in days:
            days[day] = Day(day)
        days[day].add(stamp.hour, match.group("addr"), match.group("status"),
                      match.group("bytes"), match.group("agent"), match.group("request"))
    for old in sorted(days):
        yield days.pop(old).summary()


def write_day(directory, summary):
    """Write a day's summary as <directory>/<day>.json, replacing any earlier one."""
    path = os.path.join(directory, summary["day"] + ".json")
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(summary, f, sort_keys=True, indent=1)
        f.write("\n")
    os.replace(temporary, path)
    return path
