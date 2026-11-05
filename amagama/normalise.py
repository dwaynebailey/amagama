#
# Copyright (C) amaGama contributors.
#
# This file is part of amaGama. It is distributed under the GPL3 or
# later license. See the LICENSE file for a copy of the license and
# the AUTHORS.md file for copyright and authorship information.


"""Functionality for text normalisation."""

import re

# An entity's "&" (in "&amp;") is no accelerator marker.
_ENTITY_RE = re.compile(r'&(?:[A-Za-z][\w.-]*|#[0-9]+|#[xX][0-9A-Fa-f]+);')


def indexing_version(s, checker=None):
    """Transform the given string to something more suitable for indexing."""
    s = strip_accelerator(s, checker)
    s = fix_ellipses(s)
    return s


def strip_accelerator(s, checker):
    if not (checker and checker.config.accelmarkers):
        return s

    accel = checker.config.accelmarkers[0]
    plain = _ENTITY_RE.sub(lambda m: ' ' * len(m.group()), s) if accel == '&' else s
    if plain.count(accel) != 1:
        return s

    accel_pos = plain.find(accel)
    accel_char = s[accel_pos+1:accel_pos+2]
    valid_accel = checker.config.sourcelang.validaccel
    if (valid_accel and accel_char in valid_accel) or accel_char.isalnum():
        return s[:accel_pos] + s[accel_pos + 1:]

    return s


def fix_ellipses(s):
    """Fix inconsistent ellipses."""
    # Note that the space before the ellipsis will cause postgres to index it
    # as a lexeme.
    if s.endswith(u'...'):
        return s[:-3] + u' …'
    else:
        return s.replace(u'…', u' …')
