#!/usr/bin/env python3
"""Secured-playlist support for TLDV.

TLDV switched their media bucket (``media-files.tldv.io``, Wasabi) from
public-read to private. The plain ``master.m3u8`` URL still returned in
``video.source`` by the watch-page API therefore answers ``403 AccessDenied``,
which is what breaks every naive HLS download.

The web player no longer uses that URL at all. It asks ``gaia.tldv.io`` for a
per-meeting playlist, which redirects to a short-lived signing service. The
playlist that comes back has presigned segment URLs, but the segment lines are
Caesar-shifted. The shift and the base URL are announced in a custom header
line::

    #TLDVCONF:<ttl-seconds>,<shift>,<base-url>

Shifting the letters of every segment line by ``<shift>`` and prefixing
``<base-url>`` yields ordinary, directly downloadable URLs that stay valid for
``<ttl-seconds>`` (48 hours at the time of writing).
"""

import re

GAIA_BASE_URL = "https://gaia.tldv.io"

# The web app sends "tldv-webapp/<version>" here. The gateway does not validate
# the version, but it does expect the header to be present.
CLIENT_HEADER = "tldv-webapp/1.0.0"

CONF_PREFIX = "#TLDVCONF:"


class PlaylistError(Exception):
    """Raised when the secured playlist cannot be fetched or decoded."""


def rot(text, shift):
    """Caesar-shift the ASCII letters of *text*, leaving everything else alone."""
    out = []
    for char in text:
        if 'a' <= char <= 'z':
            out.append(chr((ord(char) - 97 + shift) % 26 + 97))
        elif 'A' <= char <= 'Z':
            out.append(chr((ord(char) - 65 + shift) % 26 + 65))
        else:
            out.append(char)
    return ''.join(out)


def parse_conf(line):
    """Parse a ``#TLDVCONF:<ttl>,<shift>,<base-url>`` header line."""
    conf = line[len(CONF_PREFIX):]
    try:
        ttl, shift, base_url = conf.split(',', 2)
        return int(ttl), int(shift), base_url
    except ValueError as e:
        raise PlaylistError(f"Malformed {CONF_PREFIX} header: {line!r}") from e


def decode_playlist(playlist_text):
    """Turn a secured playlist into a plain one with absolute segment URLs.

    Returns a tuple of ``(playlist, ttl_seconds, segment_count)``. The
    ``#TLDVCONF`` line is dropped, every other comment line is kept verbatim.
    """
    shift = None
    base_url = None
    ttl = None
    segment_count = 0
    lines = []

    for line in playlist_text.splitlines():
        if line.startswith(CONF_PREFIX):
            ttl, shift, base_url = parse_conf(line)
            continue
        if line.startswith('#') or not line.strip():
            lines.append(line)
            continue
        if shift is None:
            raise PlaylistError(
                f"Segment line before any {CONF_PREFIX} header — "
                "playlist format changed?"
            )
        lines.append(base_url + rot(line, shift))
        segment_count += 1

    if shift is None:
        raise PlaylistError(
            f"No {CONF_PREFIX} header found. Either the playlist is already "
            "plain, or TLDV changed the obfuscation scheme."
        )
    if not segment_count:
        raise PlaylistError("Decoded playlist contains no segments")

    return '\n'.join(lines) + '\n', ttl, segment_count


def fetch_secured_playlist(session, meeting_id, auth_token, timeout=60):
    """Fetch and decode the secured playlist for *meeting_id*.

    Note the host: this endpoint lives on ``gaia.tldv.io``, not on the
    ``gw.tldv.io`` gateway that serves the watch-page API. Asking the gateway
    for it answers ``502``.
    """
    url = f"{GAIA_BASE_URL}/v1/meetings/{meeting_id}/playlist.m3u8"
    headers = {
        "Authorization": auth_token,
        "X-Tldv-Client": CLIENT_HEADER,
        "Accept": "*/*",
    }

    try:
        # The first response is a 302 to a short-lived signing service.
        response = session.get(url, headers=headers, timeout=timeout,
                               allow_redirects=True)
        response.raise_for_status()
    except Exception as e:
        raise PlaylistError(f"Could not fetch secured playlist: {e}") from e

    text = response.text
    if not text.lstrip().startswith("#EXTM3U"):
        raise PlaylistError(
            "Secured playlist endpoint did not return an m3u8 "
            f"(got {len(text)} bytes starting with {text[:40]!r})"
        )

    return decode_playlist(text)


def strip_query(url):
    """Drop the presigned query string from *url* — for readable logging."""
    return re.sub(r'\?.*$', '', url)
