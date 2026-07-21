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

Config via environment variables (or a .env file next to server.py — see
.env.example):
  ADSB_ULTRAFEEDER   base URL of the tar1090 instance   (default http://127.0.0.1)
  ADSB_RECV_LAT      receiver latitude   (default: auto from /data/receiver.json)
  ADSB_RECV_LON      receiver longitude  (default: auto from /data/receiver.json)
  ADSB_WEB_PORT      web-UI port to listen on (default 24556; alias: ADSB_PORT).
                     NOT a data port — the ADS-B source is the URL in ADSB_ULTRAFEEDER
  ADSB_CACHE_SECS    seconds to cache parsed points (default 120)
  ADSB_MAX_CHUNKS    cap number of chunks read, newest-first (default 48, 0 = all)
  ADSB_CELL_NM       de-dup grid cell size, nm   (default 1.5)
  ADSB_ALT_BIN_FT    de-dup altitude bin, ft     (default 1000)
  ADSB_MAX_RANGE_NM  drop positions farther than this, nm (default 400)
  ADSB_LOW_ALT_FT    "low altitude" threshold for the cone stat, ft (default 10000)
  ADSB_FETCH_WORKERS parallel chunk downloads (default 8; 1 = serial)
  ADSB_ANTENNA_AGL_FT antenna height above ground, ft (default 30; terrain LOS model)
  ADSB_BORDER_COLOR  state border colour, hex (default #3f82b8)
  ADSB_HOME_BORDER_COLOR  home-state border colour, hex (default #6fd6c0)
  ADSB_FOG_DENSITY   distance-fade density (default 0.0012; 0 disables it)
"""

import gzip
import json
import math
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv(path):
    """Zero-dependency .env loader: KEY=VALUE lines. A real environment variable
    always wins over the file (setdefault), matching how docker-compose behaves.
    Handles quoted values and a trailing ' # ...' inline comment."""
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip()
                if v[:1] in ("'", '"'):                 # quoted: take the quoted span
                    q = v[0]
                    end = v.find(q, 1)
                    v = v[1:end] if end != -1 else v[1:]
                else:                                   # strip a " #" inline comment
                    h = v.find(" #")
                    if h != -1:
                        v = v[:h]
                    v = v.strip()
                os.environ.setdefault(k.strip(), v)
    except FileNotFoundError:
        pass


_load_dotenv(os.path.join(HERE, ".env"))

# --- tunable config (env vars, optionally via a .env file — see .env.example) ---
ULTRAFEEDER = os.environ.get("ADSB_ULTRAFEEDER", "http://127.0.0.1").rstrip("/")
# Web-UI listen port. This is NOT an ADS-B data port — the data source is the
# full URL in ADSB_ULTRAFEEDER (any host/port). ADSB_WEB_PORT is the clearer
# name; ADSB_PORT is still honoured for back-compat.
PORT = int(os.environ.get("ADSB_WEB_PORT", os.environ.get("ADSB_PORT", "24556")))
CACHE_SECS = int(os.environ.get("ADSB_CACHE_SECS", "120"))
MAX_CHUNKS = int(os.environ.get("ADSB_MAX_CHUNKS", "48"))         # newest-first, 0=all
CELL_NM = float(os.environ.get("ADSB_CELL_NM", "1.5"))           # de-dup cell size (nm)
ALT_BIN_FT = float(os.environ.get("ADSB_ALT_BIN_FT", "1000"))    # de-dup alt bin (ft)
MAX_RANGE_NM = float(os.environ.get("ADSB_MAX_RANGE_NM", "400")) # drop positions beyond this (bad/MLAT)
LOW_ALT_FT = float(os.environ.get("ADSB_LOW_ALT_FT", "10000"))   # "low" threshold for the low-alt cone stat
FETCH_WORKERS = int(os.environ.get("ADSB_FETCH_WORKERS", "8"))   # parallel chunk downloads
ANTENNA_AGL_FT = float(os.environ.get("ADSB_ANTENNA_AGL_FT", "30"))  # antenna height above ground
                                                                 # (mast); feeds the terrain
                                                                 # line-of-sight horizon model
# --- appearance (passed through to the page) ---
BORDER_COLOR = os.environ.get("ADSB_BORDER_COLOR", "#3f82b8")        # state borders
HOME_BORDER_COLOR = os.environ.get("ADSB_HOME_BORDER_COLOR", "#6fd6c0")  # home state(s), highlighted
FOG_DENSITY = float(os.environ.get("ADSB_FOG_DENSITY", "0.0012"))   # distance fade; 0 disables it

# --- fixed constants (named, not config — changing these would be wrong/noise) ---
NM_PER_DEG = 60.0            # nautical miles per degree of latitude
FT_PER_NM = 6076.12         # feet per nautical mile
STEP = CELL_NM / NM_PER_DEG  # de-dup grid step in degrees
BEARING_BINS = 361          # one slot per integer bearing, 0..360 inclusive
GZIP_MIN_BYTES = 1400       # ~one MTU; not worth the CPU to compress smaller replies
# Field layout of each kept point (and how the client reads them back).
BRG, DIST, ALT, FIRST_SEEN = 0, 1, 2, 3

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


def _load_chunk(name):
    """Fetch + decompress + parse one history chunk (runs in a worker thread)."""
    raw = _fetch(ULTRAFEEDER + "/chunks/" + name)
    return json.loads(gzip.decompress(raw))


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


def iter_chunks(names):
    """Yield parsed history-chunk docs, downloaded/decompressed/parsed in parallel
    (network latency dominates a serial loop, especially for a remote feeder).
    Results stream in as they complete; failed chunks are logged and skipped."""
    # Never spin up more workers than there are chunks to fetch (>=1 for the pool).
    with ThreadPoolExecutor(max_workers=max(1, min(FETCH_WORKERS, len(names)))) as ex:
        futures = {ex.submit(_load_chunk, name): name for name in names}
        for fut in as_completed(futures):
            try:
                yield fut.result()
            except Exception as e:
                sys.stderr.write("chunk %s failed: %s\n" % (futures[fut], e))


def build_cones(points):
    """Per-bearing coverage reach: max ground distance at each integer bearing,
    over all altitudes (cone_all) and restricted to below LOW_ALT_FT (cone_low)."""
    cone_all = [0.0] * BEARING_BINS
    cone_low = [0.0] * BEARING_BINS
    for brg, dist, alt, *_ in points:
        bi = int(round(brg)) % BEARING_BINS
        if dist > cone_all[bi]:
            cone_all[bi] = dist
        if alt < LOW_ALT_FT and dist > cone_low[bi]:
            cone_low[bi] = dist
    return [round(v, 1) for v in cone_all], [round(v, 1) for v in cone_low]


def build_points():
    """Read recent-history chunks and return the cone payload: de-duplicated
    observations as [bearing, distance_nm, altitude_ft, first_seen_epoch], plus
    per-bearing reach."""
    rlat, rlon = receiver()
    # Receiver terms are constant for the whole run — compute once, not per row.
    rlat_r, rlon_r = math.radians(rlat), math.radians(rlon)
    sin1, cos1 = math.sin(rlat_r), math.cos(rlat_r)
    idx = _fetch_json(ULTRAFEEDER + "/chunks/chunks.json")
    names = idx.get("chunks", [])
    if MAX_CHUNKS > 0:
        names = names[-MAX_CHUNKS:]

    points = []
    seen = {}         # grid-cell coords (not raw lat/lon) -> index into points
    n_chunks = 0
    # Single pass over every observation: de-duplicate onto a coarse grid (this is
    # a coverage map, not a traffic replay) and convert each kept hit to
    # receiver-relative polar coordinates. Each kept point also carries the
    # earliest time its cell was heard (t, epoch seconds) so the client can
    # animate coverage building up over the retained window.
    for doc in iter_chunks(names):
        n_chunks += 1
        for f in doc.get("files", []):
            now_i = int(f.get("now", 0))
            for ac in f.get("aircraft", []):
                if len(ac) < 6:      # compact tar1090 row: [hex,alt,gs,trk,lat,lon,...]
                    continue
                lat, lon = ac[4], ac[5]
                if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                    continue
                alt = _alt_ft(ac[1])
                # Grid-cell coordinates, not raw lat/lon: lat/lon rounded to STEP-sized
                # cells and altitude bucketed into ALT_BIN_FT bins.
                key = (round(lat / STEP), round(lon / STEP), int(alt // ALT_BIN_FT))
                idx = seen.get(key)
                if idx is not None:                 # already have this cell —
                    if now_i and now_i < points[idx][FIRST_SEEN]:
                        points[idx][FIRST_SEEN] = now_i   # keep the earliest sighting
                    continue
                brg, dist = bearing_distance(sin1, cos1, rlat_r, rlon_r, lat, lon)
                if dist > MAX_RANGE_NM:   # discard obvious bad positions
                    continue
                seen[key] = len(points)
                points.append([round(brg, 1), round(dist, 2), int(alt), now_i])

    times = [p[FIRST_SEEN] for p in points if p[FIRST_SEEN]]
    t_min = min(times) if times else 0
    t_max = max(times) if times else 0
    cone_all, cone_low = build_cones(points)
    return {
        "ok": True,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "ultrafeeder": ULTRAFEEDER,
        "recv_lat": rlat,
        "recv_lon": rlon,
        "antenna_agl_ft": ANTENNA_AGL_FT,   # mast height for the terrain LOS model
        "border_color": BORDER_COLOR,       # appearance (client uses these)
        "home_border_color": HOME_BORDER_COLOR,
        "fog_density": FOG_DENSITY,
        "count": len(points),
        "chunks": n_chunks,
        "t_min": t_min,          # earliest / latest first-seen time in the window
        "t_max": t_max,          # (epoch seconds) — drives the timeline scrubber
        "points": points,        # [bearing, dist_nm, alt_ft, first_seen_epoch]
        "cone_all": cone_all,
        "cone_low": cone_low,
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
        elif gz_ok and "gzip" in self.headers.get("Accept-Encoding", "") and len(body) > GZIP_MIN_BYTES:
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
            elif path == "/cities":
                # Optional per-deployment city labels. A git-ignored
                # cities.local.json next to server.py overrides the page's
                # built-in list, so a site's own cities survive every update.
                # Absent (the common case) -> an empty array, never a 404, so a
                # fresh install stays quiet in the console.
                fp = os.path.join(HERE, "cities.local.json")
                body = b"[]"
                if os.path.exists(fp):
                    try:
                        with open(fp, "rb") as fh:
                            data = fh.read()
                        json.loads(data)          # validate; fall back to [] if broken
                        body = data
                    except Exception as e:
                        sys.stderr.write("cities.local.json ignored (%s)\n" % e)
                self._send(200, body, "application/json", gz_ok=False)
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
