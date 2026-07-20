#!/usr/bin/env python3
"""
ADSb-Vue — a standalone 3D volumetric antenna-reception viewer for an
Ultrafeeder / tar1090 ADS-B receiver.

It reads tar1090's rolling recent-history chunks (`/chunks/chunks.json` +
`chunk_*.gz`, which are gzip-compressed JSON), converts every aircraft
observation to (bearing, distance, altitude) relative to the receiver, and
serves both the raw point stream and a self-contained Three.js page that can
render it as a point cloud, a density voxel volume, or a coverage-envelope
shell.

Zero third-party dependencies — Python 3 standard library only.

Config via environment variables:
  ADSB_ULTRAFEEDER   base URL of the tar1090 instance   (default http://127.0.0.1)
  ADSB_RECV_LAT      receiver latitude   (default: auto from /data/receiver.json)
  ADSB_RECV_LON      receiver longitude  (default: auto from /data/receiver.json)
  ADSB_PORT          port to listen on   (default 24556)
  ADSB_CACHE_SECS    seconds to cache parsed points (default 120)
  ADSB_MAX_CHUNKS    cap number of chunks read, newest-first (default 0 = all)
"""

import gzip
import json
import math
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))

ULTRAFEEDER = os.environ.get("ADSB_ULTRAFEEDER", "http://127.0.0.1").rstrip("/")
PORT = int(os.environ.get("ADSB_PORT", "24556"))
CACHE_SECS = int(os.environ.get("ADSB_CACHE_SECS", "120"))
MAX_CHUNKS = int(os.environ.get("ADSB_MAX_CHUNKS", "48"))      # newest-first, 0=all
CELL_NM = float(os.environ.get("ADSB_CELL_NM", "1.5"))        # de-dup cell size
ALT_BIN_FT = float(os.environ.get("ADSB_ALT_BIN_FT", "1000"))  # de-dup alt bin

NM_PER_DEG = 60.0           # nautical miles per degree of latitude
FT_PER_NM = 6076.12         # feet per nautical mile
STEP = CELL_NM / NM_PER_DEG  # de-dup grid step in degrees

_recv = {"lat": None, "lon": None}
# data = parsed dict; json/gz = payload serialized once per rebuild (see _ensure)
_cache = {"ts": 0.0, "data": None, "json": None, "gz": None}
_cache_lock = threading.Lock()   # guards the (fast) cache read/write only
_build_lock = threading.Lock()   # single-flights the (slow) rebuild


def _fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "ADSb-Vue/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _fetch_json(url, timeout=20):
    return json.loads(_fetch(url, timeout))


def receiver():
    """Receiver lat/lon: env override, else tar1090 /data/receiver.json."""
    if _recv["lat"] is not None:
        return _recv["lat"], _recv["lon"]
    lat = os.environ.get("ADSB_RECV_LAT")
    lon = os.environ.get("ADSB_RECV_LON")
    if lat and lon:
        _recv["lat"], _recv["lon"] = float(lat), float(lon)
        return _recv["lat"], _recv["lon"]
    rj = _fetch_json(ULTRAFEEDER + "/data/receiver.json")
    _recv["lat"], _recv["lon"] = float(rj["lat"]), float(rj["lon"])
    return _recv["lat"], _recv["lon"]


def bearing_distance(sin1, cos1, rlat_r, rlon_r, alat, alon):
    """Initial bearing (deg, 0=N) and great-circle distance (nm).

    The receiver terms (sin/cos of its latitude, its lat/lon in radians) are
    constant across a run, so they're computed once by the caller and passed in
    rather than recomputed per aircraft row.
    """
    p2 = math.radians(alat)
    dlon = math.radians(alon) - rlon_r
    cos2 = math.cos(p2)
    cosd = math.cos(dlon)
    # bearing
    y = math.sin(dlon) * cos2
    x = cos1 * math.sin(p2) - sin1 * cos2 * cosd
    brg = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    # distance (haversine) in nm
    dlat = p2 - rlat_r
    a = math.sin(dlat / 2) ** 2 + cos1 * cos2 * math.sin(dlon / 2) ** 2
    dist_deg = math.degrees(2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
    return brg, dist_deg * NM_PER_DEG


def _alt_ft(v):
    if isinstance(v, (int, float)):
        return float(v)
    return 0.0  # "ground" / null


def build_points():
    """Read all recent-history chunks and return the cone payload."""
    rlat, rlon = receiver()
    # Receiver terms are constant for the whole run — compute once, not per row.
    rlat_r, rlon_r = math.radians(rlat), math.radians(rlon)
    sin1, cos1 = math.sin(rlat_r), math.cos(rlat_r)
    idx = _fetch_json(ULTRAFEEDER + "/chunks/chunks.json")
    names = idx.get("chunks", [])
    if MAX_CHUNKS > 0:
        names = names[-MAX_CHUNKS:]

    points = []          # [bearing, dist_nm, alt_ft]
    cone_all = [0.0] * 361   # max ground distance per integer bearing
    cone_low = [0.0] * 361   # same, restricted to < 10000 ft
    seen = set()             # (hex, rounded-lat, rounded-lon) de-dup within a run
    n_chunks = 0

    for name in names:
        try:
            raw = _fetch(ULTRAFEEDER + "/chunks/" + name)
            doc = json.loads(gzip.decompress(raw))
        except Exception as e:
            sys.stderr.write("chunk %s failed: %s\n" % (name, e))
            continue
        n_chunks += 1
        for f in doc.get("files", []):
            for ac in f.get("aircraft", []):
                # compact tar1090 array: [hex, alt, gs, track, lat, lon, ...]
                if len(ac) < 6:
                    continue
                lat, lon = ac[4], ac[5]
                if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                    continue
                alt = _alt_ft(ac[1])
                # spatial/alt de-dup onto a coarse grid: this is a coverage map,
                # not a traffic replay. CELL_NM-degree cells keep the payload and
                # render light regardless of how much history we read.
                key = (round(lat / STEP), round(lon / STEP), int(alt // ALT_BIN_FT))
                if key in seen:
                    continue
                seen.add(key)
                brg, dist = bearing_distance(sin1, cos1, rlat_r, rlon_r, lat, lon)
                if dist > 400:      # discard obvious bad positions
                    continue
                points.append([round(brg, 1), round(dist, 2), int(alt)])
                bi = int(round(brg)) % 361
                if dist > cone_all[bi]:
                    cone_all[bi] = dist
                if alt < 10000 and dist > cone_low[bi]:
                    cone_low[bi] = dist

    return {
        "ok": True,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "ultrafeeder": ULTRAFEEDER,
        "recv_lat": rlat,
        "recv_lon": rlon,
        "count": len(points),
        "chunks": n_chunks,
        "points": points,
        "cone_all": [round(v, 1) for v in cone_all],
        "cone_low": [round(v, 1) for v in cone_low],
    }


def _fresh(snap, refresh):
    return snap["json"] is not None and not refresh and (time.time() - snap["ts"]) < CACHE_SECS


def _ensure(refresh=False):
    """Return a cache snapshot with the payload already serialized + gzipped.

    Serialization and compression happen once per rebuild here, not per request,
    so hitting /cone from many tabs or a poller just re-sends the same bytes.
    """
    with _cache_lock:
        snap = dict(_cache)
    if _fresh(snap, refresh):
        return snap
    # Slow path: single-flight the rebuild. The expensive fetch/parse/serialize
    # runs outside the cache lock, so concurrent cache-hit readers never block.
    with _build_lock:
        with _cache_lock:
            snap = dict(_cache)
        if _fresh(snap, refresh):
            return snap
        data = build_points()
        raw = json.dumps(data).encode("utf-8")
        snap = {"ts": time.time(), "data": data, "json": raw, "gz": gzip.compress(raw, 6)}
        with _cache_lock:
            _cache.update(snap)
        return snap


def get_cone(refresh=False):
    return _ensure(refresh)["data"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, body, ctype, gz_ok=True, encoding=None):
        # encoding set => body is already compressed; just declare it. Otherwise
        # gzip on the fly for large-enough bodies the client accepts.
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if encoding:
            self.send_header("Content-Encoding", encoding)
        elif gz_ok and "gzip" in self.headers.get("Accept-Encoding", "") and len(body) > 1400:
            body = gzip.compress(body, 6)
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _accepts_gzip(self):
        return "gzip" in self.headers.get("Accept-Encoding", "")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        try:
            if path in ("/", "/view", "/index.html"):
                with open(os.path.join(HERE, "index.html"), "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8")
            elif path in ("/adsbvue_favicon.png", "/favicon.ico", "/adsbvue_logo.png"):
                name = "adsbvue_logo.png" if path.endswith("logo.png") else "adsbvue_favicon.png"
                fp = os.path.join(HERE, name)
                if os.path.exists(fp):
                    with open(fp, "rb") as fh:
                        self._send(200, fh.read(), "image/png", gz_ok=False)
                else:
                    self._send(404, b"", "application/octet-stream")
            elif path in ("/cone", "/data"):
                snap = _ensure("refresh=true" in query)
                # Pre-serialized + pre-gzipped at build time; just write the bytes.
                if self._accepts_gzip():
                    self._send(200, snap["gz"], "application/json", encoding="gzip")
                else:
                    self._send(200, snap["json"], "application/json", gz_ok=False)
            elif path == "/health":
                self._send(200, json.dumps({"ok": True}), "application/json")
            else:
                self._send(404, json.dumps({"ok": False, "error": "not found"}),
                           "application/json")
        except Exception as e:
            sys.stderr.write("handler error: %s\n" % e)
            self._send(500, json.dumps({"ok": False, "error": str(e)}),
                       "application/json")

    do_HEAD = do_GET

    def do_POST(self):
        # Debug-only: browser posts a canvas data-URL, we save it for headless
        # inspection. Harmless; not used by the app itself.
        if self.path.split("?", 1)[0] != "/_save":
            self._send(404, b"no", "text/plain")
            return
        import base64
        n = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(n).decode("utf-8", "replace")
        if body.startswith("data:"):
            body = body.split(",", 1)[1]
        q = self.path.split("?", 1)[1] if "?" in self.path else ""
        name = "shot"
        for kv in q.split("&"):
            if kv.startswith("name="):
                name = "".join(c for c in kv[5:] if c.isalnum() or c in "-_")
        out = "/tmp/adsb_%s.png" % (name or "shot")
        with open(out, "wb") as fh:
            fh.write(base64.b64decode(body))
        self._send(200, json.dumps({"ok": True, "path": out}), "application/json")


def main():
    print("ADSb-Vue  ultrafeeder=%s  port=%d" % (ULTRAFEEDER, PORT))
    try:
        rlat, rlon = receiver()
        print("receiver: %.6f, %.6f" % (rlat, rlon))
    except Exception as e:
        print("warning: could not read receiver.json yet (%s)" % e)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("listening on http://0.0.0.0:%d/  (view at /)" % PORT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
