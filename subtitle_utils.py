"""Parse standard HLS/DASH text subtitles into timed SRT cues.

This module does not handle authentication or keys; the caller supplies a
fetch_bytes(url) function for publicly or legitimately accessible text tracks.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class Track:
    url: str
    language: str = "und"
    name: str = "Subtitles"
    kind: str = "hls"


def hls_attrs(value):
    return {key.upper(): part.strip('"') for key, part in
            re.findall(r'([A-Za-z0-9-]+)=("[^"]*"|[^,]+)', value)}


def hls_tracks(master_text, master_url):
    """Inspect EXT-X-MEDIA for selectable subtitle playlists."""
    result = []
    for line in master_text.splitlines():
        if not line.startswith("#EXT-X-MEDIA:"):
            continue
        attrs = hls_attrs(line.split(":", 1)[1])
        if attrs.get("TYPE", "").upper() != "SUBTITLES":
            continue
        uri = attrs.get("URI")
        if not uri:
            continue
        result.append(Track(urljoin(master_url, uri),
                            attrs.get("LANGUAGE", "und"),
                            attrs.get("NAME", "Subtitles"), "hls"))
    return result


def hls_inband_captions(master_text):
    return any(line.startswith("#EXT-X-MEDIA:") and
               hls_attrs(line.partition(":")[2]).get("TYPE") == "CLOSED-CAPTIONS"
               for line in master_text.splitlines())


def dash_tracks(root, mpd_url):
    result = []
    for adaptation in root.iter():
        if adaptation.tag.split("}")[-1] != "AdaptationSet":
            continue
        content_type = adaptation.get("contentType", "")
        mime = adaptation.get("mimeType", "")
        is_text = content_type == "text" or any(token in mime.lower()
                     for token in ("text/", "ttml", "vtt", "subrip"))
        if not is_text:
            continue
        language = adaptation.get("lang", "und")
        for rep in adaptation:
            if rep.tag.split("}")[-1] != "Representation":
                continue
            base = next((child.text.strip() for child in rep
                         if child.tag.split("}")[-1] == "BaseURL" and child.text), None)
            if not base:
                continue
            combined = urljoin(mpd_url, base)
            path = combined.split("?", 1)[0].lower()
            if path.endswith((".vtt", ".ttml", ".dfxp", ".xml", ".srt")):
                result.append(Track(combined, language, "Subtitles", "dash"))
            else:
                # A fragmented MP4/wvtt or stpp representation is not a text URL.
                continue
    return result


def seconds(timestamp):
    timestamp = timestamp.strip().replace(",", ".")
    parts = timestamp.split(":")
    if not 2 <= len(parts) <= 3:
        raise ValueError("Invalid subtitle timestamp")
    try:
        values = [float(x) for x in parts]
    except ValueError:
        raise ValueError("Invalid subtitle timestamp") from None
    if any(x < 0 for x in values):
        raise ValueError("Negative subtitle timestamp")
    return values[-1] + 60 * values[-2] + (3600 * values[-3] if len(values) == 3 else 0)


def stamp(t):
    t = max(0, int(t * 1000 + 0.5))
    milliseconds = t % 1000
    whole = t // 1000
    return f"{whole//3600:02}:{(whole//60)%60:02}:{whole%60:02},{milliseconds:03}"


def cue_body(value):
    # Strip WebVTT cue annotation tags while preserving the readable text.
    value = re.sub(r"<(?:/?(?:c|v|lang|ruby|rt)[^>]*|[^>]+)>", "", value)
    return html.unescape(value.strip())


def vtt_cues(source):
    lines = source.replace("\r\n", "\n").lstrip("\ufeff").splitlines()
    cues = []
    mapping = None
    for line in lines:
        if line.upper().startswith("X-TIMESTAMP-MAP="):
            local = re.search(r"LOCAL:([0-9:.]+)", line)
            mpeg = re.search(r"MPEGTS:(\d+)", line)
            if local and mpeg:
                mapping = (seconds(local.group(1)), int(mpeg.group(1)) / 90000)
    # Cue blocks may contain an ID line before the timing line.
    blocks = re.split(r"\n[ \t]*\n", "\n".join(lines))
    time_re = re.compile(r"^\s*(\d{2}:\d{2}(?::\d{2})?\.\d{3})\s*-->\s*"
                         r"(\d{2}:\d{2}(?::\d{2})?\.\d{3})(?:\s+.*)?$")
    for block in blocks:
        rows = block.splitlines()
        for i, row in enumerate(rows):
            m = time_re.match(row)
            if not m:
                continue
            start, end = seconds(m.group(1)), seconds(m.group(2))
            content = cue_body("\n".join(rows[i+1:]))
            if 0 <= start < end and content:
                cues.append((start, end, content))
            break
    return cues, mapping


def srt_cues(source):
    blocks = re.split(r"\n\s*\n", source.replace("\r\n", "\n"))
    cues = []
    for block in blocks:
        rows = block.splitlines()
        for i, line in enumerate(rows):
            if "-->" not in line:
                continue
            left, right = line.split("-->", 1)
            try:
                start, end = seconds(left), seconds(right.strip().split()[0])
            except ValueError:
                break
            content = cue_body("\n".join(rows[i+1:]))
            if 0 <= start < end and content:
                cues.append((start, end, content))
            break
    return cues


def ttml_cues(source):
    root = ET.fromstring(source)
    result = []
    for el in root.iter():
        if el.tag.split("}")[-1] != "p":
            continue
        start = el.attrib.get("begin")
        end = el.attrib.get("end")
        if not start or not end:
            continue
        text = html.unescape("".join(el.itertext()).strip())
        if not text:
            continue
        try:
            # Standard clock-time expressions (other TTML timebases unsupported).
            a, b = seconds(start), seconds(end)
        except ValueError:
            continue
        if 0 <= a < b:
            result.append((a, b, text))
    return result


def make_srt(cues, destination, limit=None):
    ordered = sorted(set((round(a,3), round(b,3),t)
                         for a,b,t in cues if t.strip()), key=lambda x:(x[0],x[1]))
    parts = []
    for a,b,t in ordered:
        if limit is not None:
            if a >= limit:
                continue
            b = min(b, limit)
        if b <= a:
            continue
        parts.append(f"{len(parts)+1}\n{stamp(a)} --> {stamp(b)}\n{t}\n")
    if not parts:
        return 0
    Path(destination).write_text("\n".join(parts), encoding="utf-8")
    return len(parts)


def materialize(track, fetch_bytes, folder, seconds_limit=None):
    """Download plain-text subtitle assets through caller's existing session.

    Does not handle encrypted subtitle playlists or in-band broadcast captions.
    """
    body = fetch_bytes(track.url).decode("utf-8-sig")
    url_path = track.url.split("?", 1)[0].lower()
    cues = []
    if "#EXTM3U" in body[:100] or url_path.endswith(".m3u8"):
        refs = []
        at = 0.0
        duration = None
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("#EXT-X-KEY") and "METHOD=NONE" not in line:
                raise ValueError("Encrypted subtitle playlist not supported")
            if line.startswith("#EXTINF:"):
                duration = float(line.split(":",1)[1].split(",",1)[0])
            elif line and not line.startswith("#") and duration is not None:
                refs.append((urljoin(track.url,line),at,duration))
                at += duration
                duration = None
        if not refs:
            raise ValueError("Subtitle playlist has no text segments")
        base_map_time = None
        for url, offset, segment_duration in refs:
            if seconds_limit is not None and offset > seconds_limit + segment_duration:
                break
            payload = fetch_bytes(url).decode("utf-8-sig")
            selected, mapping = vtt_cues(payload)
            if mapping:
                local, mpeg = mapping
                if base_map_time is None:
                    base_map_time = mpeg - local
                for a,b,t in selected:
                    delta = mpeg - local - base_map_time
                    cues.append((a+delta,b+delta,t))
            else:
                for a,b,t in selected:
                    adjustment = offset if offset > 0.5 and a < offset - 0.25 else 0
                    cues.append((a+adjustment,b+adjustment,t))
    elif (url_path.endswith((".xml",".ttml",".dfxp"))
          or body.lstrip().startswith(("<?xml","<tt ", "<tt>"))):
        cues = ttml_cues(body)
    elif url_path.endswith(".srt"):
        cues = srt_cues(body)
    else:
        cues, _ = vtt_cues(body)
    output = Path(folder) / "subtitles.srt"
    n = make_srt(cues,output,seconds_limit)
    if not n:
        raise ValueError("No subtitle cues were found")
    return output, n
