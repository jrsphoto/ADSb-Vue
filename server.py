#!/usr/bin/env python3
"""
ADSb-Vue — a standalone 3D volumetric antenna-reception viewer for an
Ultrafeeder / tar1090 ADS-B receiver.

It converts every aircraft observation to (bearing, distance, altitude)
relative to the receiver and serves both the raw point stream and a
self-contained Three.js page that can render it as a point cloud, a density
voxel volume, or a coverage-envelope shell.

Ingest is a background thread reading `/data/aircraft.json` every few seconds.
It records continuously, whether or not anyone has the page open. Every decoder
serves that endpoint, so this works with dump1090-fa and dump1090-mutability as
well as tar1090, and the resolution does not depend on the feeder's config.

Polling has no history of its own, so at startup it reads tar1090's history
chunks once to fill in the map, and again after downtime to fill the gap. A
feeder with no /chunks/ simply starts from now.

Zero third-party dependencies — Python 3 standard library only.

Config via environment variables (or a .env file next to server.py — see
.env.example):
  ADSB_ULTRAFEEDER   base URL of the tar1090 instance   (default http://127.0.0.1)
  ADSB_RECV_LAT      receiver latitude   (default: auto from /data/receiver.json)
  ADSB_RECV_LON      receiver longitude  (default: auto from /data/receiver.json)
  ADSB_WEB_PORT      web-UI port to listen on (default 24556; alias: ADSB_PORT).
                     NOT a data port — the ADS-B source is the URL in ADSB_ULTRAFEEDER
  ADSB_CACHE_SECS    seconds to cache parsed points (default 120)
  ADSB_POLL_SECS     seconds between aircraft.json reads (default 5)
  ADSB_FLUSH_SECS    seconds between batched writes to the store (default 60)
  ADSB_MAX_CHUNKS    how much history the startup fill reads, newest-first
                     (default 48, 0 = all). A one-time cost, so bigger is cheap
  ADSB_CELL_NM       de-dup grid cell size, nm   (default 1.5)
  ADSB_ALT_BIN_FT    de-dup altitude bin, ft     (default 1000)
  ADSB_MAX_RANGE_NM  drop positions farther than this, nm (default 400)
  ADSB_LOW_ALT_FT    "low altitude" threshold for the cone stat, ft (default 10000)
  ADSB_FETCH_WORKERS parallel chunk downloads (default 8; 1 = serial)
  ADSB_ANTENNA_AGL_FT antenna height above ground, ft (default 30; terrain LOS model)
  ADSB_ANTENNA_ELEV_FT ground elevation of the receiver site, ft MSL (default 0).
                     Used with ADSB_ANTENNA_AGL_FT for the LOS filter below.
  ADSB_LOS_FILTER    drop observations whose distance exceeds the 4/3-earth
                     line-of-sight range for the reported altitude (default off).
                     Useful when the upstream decoder occasionally accepts weak
                     signals with bit-corrupted altitude fields — physically
                     impossible far low-altitude cells get rejected at ingest.
  ADSB_BORDER_COLOR  state border colour, hex (default #3f82b8)
  ADSB_HOME_BORDER_COLOR  home-state border colour, hex (default #6fd6c0)
  ADSB_FOG_DENSITY   distance-fade density (default 0.0012; 0 disables it)
  ADSB_MAP_BEHIND_CONE  draw map borders and city labels behind the coverage
                     volume instead of over it (default off)
  ADSB_DATA_DIR      persistence volume: if set, coverage accumulates in
                     <dir>/adsbvue.db across restarts, and cities.local.json is
                     read from <dir> first. Unset = no persistence (default).
  ADSB_RETAIN_DAYS   store retention: drop cells not heard within N days
                     (default 30; 0 = keep everything)
  ADSB_HEYWHATSTHAT_ID  HeyWhatsThat panorama id for your site (unset = off);
                     serves its horizon rings at /hwt, fetched once + cached
  ADSB_HEYWHATSTHAT_ALTS_FT  ring altitudes, ft (default 10000,40000)
"""

import gzip
import json
import math
import os
import signal
import sqlite3
import sys
import threading
import time
import urllib.error
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
# Poll interval. An aircraft at 500 kt covers 0.139 nm/s, so a cell of CELL_NM is
# crossed in CELL_NM / 0.139 seconds. Polling faster than that only re-reads
# positions that de-dup into a cell already recorded. 5 s suits the 1.0-1.5 nm
# cell sizes people actually run; raise it for a coarser grid or a busy Pi.
POLL_SECS = float(os.environ.get("ADSB_POLL_SECS", "5"))
# Write batching. Polls accumulate in memory and land in SQLite every
# FLUSH_SECS, which at the defaults is ~12x fewer transactions than writing per
# poll, which is worth doing on a Pi's SD card. An unclean shutdown loses at
# most this many seconds of coverage, nothing for a map that builds over days.
FLUSH_SECS = float(os.environ.get("ADSB_FLUSH_SECS", "60"))
MAX_CHUNKS = int(os.environ.get("ADSB_MAX_CHUNKS", "48"))         # newest-first, 0=all
CELL_NM = float(os.environ.get("ADSB_CELL_NM", "1.5"))           # de-dup cell size (nm)
ALT_BIN_FT = float(os.environ.get("ADSB_ALT_BIN_FT", "1000"))    # de-dup alt bin (ft)
MAX_RANGE_NM = float(os.environ.get("ADSB_MAX_RANGE_NM", "400")) # drop positions beyond this (bad/MLAT)
LOW_ALT_FT = float(os.environ.get("ADSB_LOW_ALT_FT", "10000"))   # "low" threshold for the low-alt cone stat
FETCH_WORKERS = int(os.environ.get("ADSB_FETCH_WORKERS", "8"))   # parallel chunk downloads
ANTENNA_AGL_FT = float(os.environ.get("ADSB_ANTENNA_AGL_FT", "30"))  # antenna height above ground
                                                                 # (mast); feeds the terrain
                                                                 # line-of-sight horizon model
ANTENNA_ELEV_FT = float(os.environ.get("ADSB_ANTENNA_ELEV_FT", "0"))  # ground elev of the site
                                                                 # (ft MSL); + AGL for the LOS filter
LOS_FILTER = os.environ.get("ADSB_LOS_FILTER", "false").lower() in ("1", "true", "yes", "on")
# 4/3-earth line-of-sight: max_nm = 1.23 * (sqrt(alt_ft) + sqrt(antenna_MSL_ft)) * 1.15.
# Precompute the constant terms so the per-observation check is one sqrt + one multiply-add.
_LOS_K = 1.23 * 1.15                                             # ≈ 1.4145
_LOS_ANT_TERM = _LOS_K * math.sqrt(max(0.0, ANTENNA_ELEV_FT + ANTENNA_AGL_FT))
# --- appearance (passed through to the page) ---
BORDER_COLOR = os.environ.get("ADSB_BORDER_COLOR", "#3f82b8")        # state borders
HOME_BORDER_COLOR = os.environ.get("ADSB_HOME_BORDER_COLOR", "#6fd6c0")  # home state(s), highlighted
FOG_DENSITY = float(os.environ.get("ADSB_FOG_DENSITY", "0.0012"))   # distance fade; 0 disables it
# Map borders and city labels are normally drawn over everything, so they stay
# readable through the coverage volume. Seen from a low side angle that puts the
# whole distant map, squashed into a band at the horizon, on top of the cone.
# Setting this makes them respect what is in front of them instead. Off by
# default because always-visible geography is the long-standing look.
MAP_BEHIND_CONE = os.environ.get("ADSB_MAP_BEHIND_CONE", "false").lower() in ("1", "true", "yes", "on")
# --- persistence (optional) ---
DATA_DIR = os.environ.get("ADSB_DATA_DIR", "").strip()   # volume dir; unset = no store
STORE_PATH = os.path.join(DATA_DIR, "adsbvue.db") if DATA_DIR else None
RETAIN_DAYS = int(os.environ.get("ADSB_RETAIN_DAYS", "30"))  # store: drop cells not
                                                            # heard within N days (0 = keep all)
# --- HeyWhatsThat range rings (optional) ---
HWT_ID = os.environ.get("ADSB_HEYWHATSTHAT_ID", "").strip()      # panorama id; unset = off
HWT_ALTS_FT = os.environ.get("ADSB_HEYWHATSTHAT_ALTS_FT", "10000,40000")  # ring altitudes
if DATA_DIR:
    os.makedirs(DATA_DIR, exist_ok=True)

# --- fixed constants (named, not config — changing these would be wrong/noise) ---
NM_PER_DEG = 60.0            # nautical miles per degree of latitude
FT_PER_NM = 6076.12         # feet per nautical mile
STEP = CELL_NM / NM_PER_DEG  # de-dup grid step in degrees
BEARING_BINS = 361          # one slot per integer bearing, 0..360 inclusive
GZIP_MIN_BYTES = 1400       # ~one MTU; not worth the CPU to compress smaller replies
# Field layout of a kept point. The client sees the first four; LAST_SEEN is an
# internal accumulator (used to merge/retain in the persistent store).
BRG, DIST, ALT, FIRST_SEEN, LAST_SEEN = 0, 1, 2, 3, 4

_recv = {"pos": None}            # (lat, lon) once resolved; one tuple, so a reader
_recv_lock = threading.Lock()    # never sees a half-written pair (poller + requests)
# json/gz = the payload serialized and compressed once per rebuild (see _ensure).
# The parsed dict is deliberately NOT kept: nothing reads it, and at 1.5M cells
# it is ~310 MB of Python objects.
_cache = {"ts": 0.0, "json": None, "gz": None}
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
    pos = _recv["pos"]
    if pos is not None:
        return pos
    lat = os.environ.get("ADSB_RECV_LAT")
    lon = os.environ.get("ADSB_RECV_LON")
    if lat and lon:
        pos = (float(lat), float(lon))
    else:
        rj = _fetch_json(ULTRAFEEDER + "/data/receiver.json")
        pos = (float(rj["lat"]), float(rj["lon"]))
    with _recv_lock:
        _recv["pos"] = pos
    return pos


def receiver_trig():
    """Receiver position plus the trig terms every conversion needs.

    sin/cos of the receiver latitude and its lat/lon in radians are constant for
    a run, so they're computed here once per ingest pass rather than per row.
    """
    rlat, rlon = receiver()
    rlat_r, rlon_r = math.radians(rlat), math.radians(rlon)
    return rlat, rlon, (math.sin(rlat_r), math.cos(rlat_r), rlat_r, rlon_r)


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


def merge_obs(cells, trig, lat, lon, alt, now_i):
    """De-duplicate one observation onto the coarse coverage grid.

    Both ingest paths go through here, so a cell key means exactly the same
    thing whether the observation arrived in a history chunk or a live
    aircraft.json poll. The two sources have to be able to share a store.

    `cells` maps grid-cell coords -> [brg, dist, alt, first_seen, last_seen]:
    lat/lon rounded to STEP-sized cells, altitude bucketed into ALT_BIN_FT bins.
    A cell already present is only re-timed; the trig is skipped entirely.
    """
    key = (round(lat / STEP), round(lon / STEP), int(alt // ALT_BIN_FT))
    rec = cells.get(key)
    if rec is not None:                 # already have this cell —
        if now_i:
            if now_i < rec[FIRST_SEEN]:
                rec[FIRST_SEEN] = now_i
            if now_i > rec[LAST_SEEN]:
                rec[LAST_SEEN] = now_i
        return
    sin1, cos1, rlat_r, rlon_r = trig
    brg, dist = bearing_distance(sin1, cos1, rlat_r, rlon_r, lat, lon)
    if dist > MAX_RANGE_NM:   # discard obvious bad positions
        return
    # Optional 4/3-earth LOS filter: an aircraft at `alt` can't be heard farther
    # than 1.23 * (sqrt(alt) + sqrt(antenna_MSL)) * 1.15 nm. Weak decodes with
    # bit-corrupted altitude fields land in low bins at physically impossible
    # distances — this rejects them at ingest.
    if LOS_FILTER and dist > _LOS_K * math.sqrt(max(0.0, alt)) + _LOS_ANT_TERM:
        return
    cells[key] = [round(brg, 1), round(dist, 2), int(alt), now_i, now_i]


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


def cities_file():
    """Path to the city-label file in effect, by precedence:
      1. cities.local.json on the data volume  (edit it live to override)
      2. cities.local.json baked next to server.py
      3. cities.local.json.example  (the shipped comprehensive worldwide default,
         so a fresh install shows nearby labels with no config)
    ...or None if somehow none exist."""
    candidates = []
    if DATA_DIR:
        candidates.append(os.path.join(DATA_DIR, "cities.local.json"))
    candidates.append(os.path.join(HERE, "cities.local.json"))
    candidates.append(os.path.join(HERE, "cities.local.json.example"))
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


_hwt = {"bytes": None, "fail_ts": 0.0}
_hwt_lock = threading.Lock()
HWT_RETRY_SECS = 600     # after a failed fetch, don't re-hit their API for 10 min


def _hwt_requested_alts_m():
    """The current ADSB_HEYWHATSTHAT_ALTS_FT as a set of ints (metres, rounded).
    Used both to build the fetch URL and to detect stale cache from a prior
    config that requested different altitudes."""
    out = set()
    for a in HWT_ALTS_FT.split(","):
        a = a.strip()
        if not a:
            continue
        try:
            out.add(int(round(float(a) * 0.3048)))
        except ValueError:
            pass
    return out


def _hwt_cached_alts_m(data):
    """Alts (metres, ints) present in a cached HWT payload. HWT returns each
    ring's alt as a string; coerce to int. Empty set on any parse trouble so
    the caller treats the cache as unusable and refetches."""
    try:
        d = json.loads(data)
        out = set()
        for r in d.get("rings", []):
            try:
                out.add(int(round(float(r.get("alt", 0)))))
            except (TypeError, ValueError):
                pass
        return out
    except Exception:
        return set()


def _hwt_payload():
    """HeyWhatsThat horizon rings as JSON bytes ({} when unconfigured). The
    panorama is static for a site, so fetch it once and cache it: in memory and,
    when a data volume exists, on disk, out of respect for their free API.
    The cache invalidates automatically if the ADSB_HEYWHATSTHAT_ALTS_FT config
    has changed since the cached payload was fetched."""
    if not HWT_ID:
        return b"{}"
    want = _hwt_requested_alts_m()
    with _hwt_lock:
        if _hwt["bytes"] and _hwt_cached_alts_m(_hwt["bytes"]) == want:
            return _hwt["bytes"]
        cache = os.path.join(DATA_DIR, "hwt_%s.json" % HWT_ID) if DATA_DIR else None
        if cache and os.path.exists(cache):
            try:
                with open(cache, "rb") as fh:
                    data = fh.read()
                json.loads(data)               # validate; refetch if corrupt
                if _hwt_cached_alts_m(data) == want:
                    _hwt["bytes"] = data
                    return data
                # else fall through to refetch: config changed since cache was written
            except Exception:
                pass
        if time.time() - _hwt["fail_ts"] < HWT_RETRY_SECS:
            return b"{}"
        alts_m = ",".join(str(a) for a in sorted(want))
        url = ("https://www.heywhatsthat.com/api/upintheair.json"
               "?id=%s&refraction=0.25&alts=%s" % (HWT_ID, alts_m))
        try:
            data = _fetch(url)
            json.loads(data)
            _hwt["bytes"] = data
            if cache:
                with open(cache, "wb") as fh:
                    fh.write(data)
            return data
        except Exception as e:
            _hwt["fail_ts"] = time.time()
            sys.stderr.write("heywhatsthat fetch failed: %s\n" % e)
            return b"{}"


def seed_data_dir():
    """First run with a volume: if there's a baked-in cities.local.json but none on
    the volume yet, copy it over so the volume holds the canonical, live-editable
    copy. Never overwrites an existing one."""
    if not DATA_DIR:
        return
    dst = os.path.join(DATA_DIR, "cities.local.json")
    src = os.path.join(HERE, "cities.local.json")
    if os.path.exists(src) and not os.path.exists(dst):
        try:
            import shutil
            shutil.copyfile(src, dst)
            sys.stderr.write("seeded cities.local.json onto %s\n" % DATA_DIR)
        except Exception as e:
            sys.stderr.write("cities seed skipped: %s\n" % e)


def _store_conn():
    # An explicit busy timeout rather than relying on the 5 s default: under WAL
    # a reader never blocks the writer, but two writers still serialise, and the
    # retention DELETE is a full table scan (~100 ms at 1.5M rows) that holds the
    # write lock while it runs.
    con = sqlite3.connect(STORE_PATH, timeout=30.0)
    con.execute("PRAGMA journal_mode=WAL")   # crash-safe, no full-file rewrites
    con.execute(
        "CREATE TABLE IF NOT EXISTS cells("
        "klat INTEGER, klon INTEGER, kalt INTEGER,"          # grid-cell key
        "brg REAL, dist REAL, alt INTEGER,"                  # the point we serve
        "first_seen INTEGER, last_seen INTEGER,"             # accumulate / retain
        "PRIMARY KEY(klat, klon, kalt))")
    return con


def _store_upsert(cells):
    """Upsert a batch of cells into the persistent store, keeping the earliest
    first_seen and the latest last_seen, then apply retention. One transaction.

    Called both by a /cone rebuild (chunk mode) and by the background poller's
    periodic flush, so it does the write and nothing else."""
    con = _store_conn()
    try:
        with con:   # one transaction
            con.executemany(
                "INSERT INTO cells(klat,klon,kalt,brg,dist,alt,first_seen,last_seen) "
                "VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(klat,klon,kalt) DO UPDATE SET "
                "first_seen=min(first_seen, excluded.first_seen), "
                "last_seen=max(last_seen, excluded.last_seen)",
                [(k[0], k[1], k[2], r[BRG], r[DIST], r[ALT], r[FIRST_SEEN], r[LAST_SEEN])
                 for k, r in cells.items()])
            if RETAIN_DAYS > 0:   # rolling window: drop cells not heard recently
                cutoff = int(time.time()) - RETAIN_DAYS * 86400
                con.execute("DELETE FROM cells WHERE last_seen < ?", (cutoff,))
    finally:
        con.close()


def _store_read_all():
    """The whole accumulated coverage as [brg, dist, alt, first_seen] points,
    plus the first-seen span."""
    con = _store_conn()
    try:
        points = [[b, d, a, fs] for (b, d, a, fs)
                  in con.execute("SELECT brg,dist,alt,first_seen FROM cells")]
        lo, hi = con.execute(
            "SELECT min(first_seen), max(first_seen) FROM cells WHERE first_seen>0").fetchone()
    finally:
        con.close()
    return points, lo or 0, hi or 0


def _merge_cells(dst, src):
    """Fold src's cells into dst, widening each cell's first/last-seen span."""
    for key, r in src.items():
        cur = dst.get(key)
        if cur is None:
            dst[key] = list(r)
            continue
        if r[FIRST_SEEN] and (not cur[FIRST_SEEN] or r[FIRST_SEEN] < cur[FIRST_SEEN]):
            cur[FIRST_SEEN] = r[FIRST_SEEN]
        if r[LAST_SEEN] > cur[LAST_SEEN]:
            cur[LAST_SEEN] = r[LAST_SEEN]


class NoChunkHistory(Exception):
    """The feeder serves no /chunks/ endpoint. Expected on dump1090-fa and
    dump1090-mutability, which is exactly why poll mode is the default."""


def read_chunks(trig):
    """Read the newest history chunks into a fresh cell dict.

    Returns (cells, chunks_read). Each cell tracks the earliest and latest time
    it was heard — first_seen drives the timeline; last_seen drives store
    retention.
    """
    try:
        idx = _fetch_json(ULTRAFEEDER + "/chunks/chunks.json")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Almost always dump1090-fa or dump1090-mutability, which serve
            # aircraft.json but have no history endpoint. Raised as its own type
            # so each caller can say something useful: the seed treats it as a
            # thinner start, chunk mode treats it as misconfiguration.
            raise NoChunkHistory(
                "no /chunks/ on %s: dump1090-fa and dump1090-mutability do not "
                "provide one" % ULTRAFEEDER)
        raise
    names = idx.get("chunks", [])
    if MAX_CHUNKS > 0:
        names = names[-MAX_CHUNKS:]
    cells = {}        # grid-cell coords -> [brg, dist, alt, first_seen, last_seen]
    n_chunks = 0
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
                merge_obs(cells, trig, lat, lon, _alt_ft(ac[1]), now_i)
    return cells, n_chunks


SEED_FRESH_SECS = 120    # store newer than this: no gap worth a history read


class Poller:
    """Background ingest: reads the live aircraft list on a timer and batches
    what it finds into the store.

    All of the poller's mutable state lives on the instance rather than in
    module globals. That removes the reassign-a-global dance the flush used to
    need, and turns what were dict keys into attributes, so a typo is an error
    instead of quietly creating a new field nobody reads.

    `pending` holds cells read but not yet written. Without a data volume there
    is nowhere to write them to, so it simply keeps growing and *is* the
    accumulated coverage, lost on restart, exactly as the no-persistence path
    has always behaved.
    """

    STALE_FACTOR = 6     # /health flags the poller stale after this many missed reads

    def __init__(self):
        self.pending = {}
        self.lock = threading.Lock()
        self.started = 0.0      # when the thread came up
        self.last_ok = 0.0      # epoch of the last successful read
        self.last_flush = 0.0   # epoch of the last write to the store
        self.polls = 0
        self.errors = 0
        self.aircraft = 0       # positioned aircraft in the last successful read
        self.last_error = ""
        self.seeded = 0
        self._stop = threading.Event()
        self._thread = None

    # --- ingest ---------------------------------------------------------

    def read_once(self):
        """Read /data/aircraft.json once, merging every positioned aircraft into
        `pending`. Returns the number of positioned aircraft seen.

        A position in this file can be up to a minute old (readsb keeps an
        aircraft listed for a while after its last position report), so the
        observation time is `now - seen_pos`, not `now`. Recording a stale
        position as heard-just-now would smear the timeline.
        """
        _, _, trig = receiver_trig()
        doc = _fetch_json(ULTRAFEEDER + "/data/aircraft.json", timeout=10)
        now = float(doc.get("now") or time.time())
        n = 0
        with self.lock:
            for ac in doc.get("aircraft", []):
                lat, lon = ac.get("lat"), ac.get("lon")
                if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                    continue
                # alt_baro is the field tar1090's chunks carry, and "ground"
                # reads as 0 ft. Fall back to alt_geom so an aircraft reporting
                # only geometric altitude isn't silently filed at ground level.
                alt = ac.get("alt_baro")
                if alt is None:
                    alt = ac.get("alt_geom")
                seen = ac.get("seen_pos")
                t = now - seen if isinstance(seen, (int, float)) else now
                merge_obs(self.pending, trig, lat, lon, _alt_ft(alt), int(t))
                n += 1
        return n

    def seed(self):
        """Fill the store from tar1090 history once at startup, so the map does
        not begin blank. Returns cells seeded.

        Polling only knows what it has watched. On a first run that means an
        empty map, which reads as "the tool is broken", and after downtime it
        means a permanent hole. One history read covers both.

        Skipped when the store already holds recent data, so a quick restart
        does not re-read history it already has.

        Non-fatal by design. dump1090-fa and dump1090-mutability have no
        /chunks/ endpoint at all and polling works perfectly well without a
        seed, so a failure here is reported and ignored rather than blocking
        ingest. That is what makes those decoders usable.
        """
        newest = 0
        if STORE_PATH and os.path.exists(STORE_PATH):
            try:
                con = _store_conn()
                try:
                    newest = con.execute("SELECT max(last_seen) FROM cells").fetchone()[0] or 0
                finally:
                    con.close()
            except Exception as e:
                sys.stderr.write("seed: could not read store (%s)\n" % e)
        gap = time.time() - newest
        if newest and gap < SEED_FRESH_SECS:
            print("seed: store is current (%.0fs old), skipping history read" % gap)
            return 0
        try:
            _, _, trig = receiver_trig()
            cells, n_chunks = read_chunks(trig)
        except NoChunkHistory:
            # Expected on dump1090-fa. Not a problem and not misconfiguration:
            # the map just starts from now instead of from history.
            print("seed: this feeder keeps no history, so the map starts from now "
                  "and builds as aircraft are heard")
            return 0
        except Exception as e:
            # Feeder not up yet, network blip, whatever it is: polling still
            # works, it just starts thinner. Not worth failing over.
            sys.stderr.write("seed: history read skipped (%s)\n" % e)
            return 0
        if not cells:
            return 0
        if STORE_PATH:
            _store_upsert(cells)
        else:
            with self.lock:
                _merge_cells(self.pending, cells)
        why = "cold start" if not newest else "filling a %.0f min gap" % (gap / 60)
        print("seed: %s, read %d chunks into %d cells of history"
              % (why, n_chunks, len(cells)))
        return len(cells)

    # --- writing --------------------------------------------------------

    def flush(self):
        """Move the accumulated batch into the store, returning cells written.

        A no-op without a store: there, `pending` IS the accumulated coverage,
        so draining it would throw the map away. If the write fails the batch
        goes back rather than being lost.
        """
        if not STORE_PATH:
            return 0
        with self.lock:
            batch, self.pending = self.pending, {}
        # Note this proceeds even when batch is empty. _store_upsert also applies
        # retention, and a receiver that has gone quiet still needs its old cells
        # aged out. Since /cone no longer does it, this is the only place it
        # happens.
        try:
            _store_upsert(batch)
        except Exception:
            with self.lock:
                _merge_cells(batch, self.pending)
                self.pending = batch
            raise
        self.last_flush = time.time()
        return len(batch)

    def snapshot(self):
        """The pending cells as a finished payload triple, for the no-store path
        where they are the entire map.

        Projects inside the lock rather than handing back a dict. dict() is a
        shallow copy, so the caller would still be holding the *same* mutable
        [brg, dist, alt, first_seen, last_seen] lists the poller keeps updating.
        Nothing could corrupt (only the two timestamps are ever mutated, and a
        list-item assignment is atomic), but walking them twice outside the lock
        meant a point's first_seen could disagree with the t_min derived from it.
        One pass under the lock is both consistent and cheaper.
        """
        with self.lock:
            points, times = [], []
            for r in self.pending.values():
                points.append([r[BRG], r[DIST], r[ALT], r[FIRST_SEEN]])
                if r[FIRST_SEEN]:
                    times.append(r[FIRST_SEEN])
        return points, (min(times) if times else 0), (max(times) if times else 0)

    # --- lifecycle ------------------------------------------------------

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="adsbvue-poll",
                                        daemon=True)
        self._thread.start()
        print("ingest: polling %s/data/aircraft.json every %gs, flush every %gs"
              % (ULTRAFEEDER, POLL_SECS, FLUSH_SECS))

    def stop(self, timeout=10.0):
        """Ask the thread to finish and wait for it. Returns True if it stopped.

        Called before the final flush on shutdown. Without it the thread is a
        daemon that keeps reading right up until the interpreter exits, so it
        could add cells immediately *after* that last flush and lose them, up to
        one poll interval's worth. Nothing corrupts either way (the drain is
        atomic under the lock, and SQLite rolls back a transaction interrupted
        at exit), but this makes shutdown deterministic rather than merely
        survivable.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        return True

    def _loop(self):
        """Read on the poll interval, write on the slower flush interval.

        Seeds first. That happens here rather than in main() so a slow or
        unreachable feeder delays ingest only, never the web server coming up.
        """
        self.started = time.time()
        try:
            self.seeded = self.seed()
        except Exception as e:
            sys.stderr.write("seed failed: %s\n" % e)
        next_flush = time.time() + FLUSH_SECS
        while not self._stop.is_set():
            t0 = time.time()
            try:
                self.aircraft = self.read_once()
                self.polls += 1
                self.last_ok = t0
                self.last_error = ""
            except Exception as e:
                self.errors += 1
                self.last_error = str(e)
                sys.stderr.write("aircraft.json poll failed: %s\n" % e)
            if time.time() >= next_flush:
                try:
                    n = self.flush()
                    if n:
                        sys.stderr.write("poll: flushed %d cells to the store\n" % n)
                except Exception as e:
                    sys.stderr.write("poll: store flush failed: %s\n" % e)
                next_flush = time.time() + FLUSH_SECS
            # Wait out the remainder of the interval so a slow read doesn't make
            # the cadence drift longer and longer. Event.wait rather than sleep,
            # so a shutdown does not have to sit through a whole interval.
            self._stop.wait(max(0.5, POLL_SECS - (time.time() - t0)))

    # --- reporting ------------------------------------------------------

    def health(self):
        """Poller status for /health."""
        last_ok = self.last_ok
        # Age is measured from the last good read, or from thread start if there
        # has never been one, so a poller that has never succeeded still goes
        # stale rather than looking healthy forever.
        since = time.time() - (last_ok or self.started or time.time())
        out = {
            "poll_secs": POLL_SECS,
            "flush_secs": FLUSH_SECS,
            "last_poll": int(last_ok) if last_ok else None,
            "last_poll_iso": (time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(last_ok))
                              if last_ok else None),
            "last_poll_age_secs": round(since, 1),
            "poll_ok": since < POLL_SECS * self.STALE_FACTOR,
            "polls": self.polls,
            "poll_errors": self.errors,
            "aircraft": self.aircraft,
            "pending_cells": len(self.pending),
            "last_flush": int(self.last_flush) if self.last_flush else None,
        }
        if self.last_error:
            out["last_error"] = self.last_error
        return out


POLLER = Poller()


def build_points():
    """Build the cone payload: de-duplicated observations as
    [bearing, distance_nm, altitude_ft, first_seen_epoch], plus per-bearing reach.

    This is a read, not an ingest: the poller thread has already done the
    recording. With ADSB_DATA_DIR set the payload is the whole accumulated
    store; without it, whatever the poller is holding in memory.

    It writes nothing. It used to call _store_upsert({}) here, whose only effect
    with an empty batch was to redo the retention DELETE that the poller already
    runs on every flush. That took the write lock for ~100 ms per page load at
    1.5M rows, for nothing. With that gone /cone is a pure reader, and under WAL
    a reader never contends with the poller's writes at all.

    Still worth single-flighting behind _build_lock: a large store means
    selecting a million-plus rows and then serialising and gzipping them, which
    two concurrent requests should not both do.
    """
    rlat, rlon = receiver()
    # Land the newest polls before reading, so an explicit ?refresh=true is
    # never answered with data a whole flush interval stale.
    POLLER.flush()

    if STORE_PATH:
        points, t_min, t_max = _store_read_all()
    else:
        points, t_min, t_max = POLLER.snapshot()   # no store: pending IS the map
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
        "map_behind_cone": MAP_BEHIND_CONE,
        "count": len(points),
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
        # Drop the point list before allocating the gzip buffer. At 1.5M cells
        # it is ~310 MB of Python objects ([brg, dist, alt, first_seen] costs
        # ~196 bytes each once you count the list and the four boxed numbers),
        # and everything downstream works from `raw`. Keeping it cached was
        # costing that much for nothing: the only reader was get_cone(), which
        # had no callers.
        del data
        snap = {"ts": time.time(), "json": raw, "gz": gzip.compress(raw, 6)}
        with _cache_lock:
            _cache.update(snap)
        return snap


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
                # cities.local.json (on the data volume if ADSB_DATA_DIR is set,
                # else next to server.py) overrides the page's built-in list, so a
                # site's own cities survive every update. Read fresh each request,
                # so editing it takes effect on the next page load. Absent (the
                # common case) -> an empty array, never a 404, so a fresh install
                # stays quiet in the console.
                fp = cities_file()
                body = b"[]"
                if fp:
                    try:
                        with open(fp, "rb") as fh:
                            data = fh.read()
                        json.loads(data)          # validate; fall back to [] if broken
                        body = data
                    except Exception as e:
                        sys.stderr.write("cities.local.json ignored (%s)\n" % e)
                self._send(200, body, "application/json", gz_ok=False)
            elif path == "/hwt":
                # HeyWhatsThat horizon rings (fetched once + cached); {} when
                # ADSB_HEYWHATSTHAT_ID is unset, never a 404.
                self._send(200, _hwt_payload(), "application/json")
            elif path == "/health":
                # "ok" stays true whenever the process is serving, so existing
                # container healthchecks behave as before. The separate
                # "poll_ok" flag reports whether the ingest thread is actually
                # still reading, with "last_poll" to see how recently. Those two
                # are what tell an operator whether a dead map means a dead
                # antenna or a dead reader.
                body = {"ok": True}
                body.update(POLLER.health())
                self._send(200, json.dumps(body), "application/json")
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


def _on_term(signum, frame):
    """Docker stops a container with SIGTERM, whose default action exits without
    unwinding. Turn it into the same KeyboardInterrupt a Ctrl-C raises so the
    shutdown path below runs and the pending poll batch reaches the store."""
    raise KeyboardInterrupt


def main():
    print("ADSb-Vue  ultrafeeder=%s  port=%d" % (ULTRAFEEDER, PORT))
    old = os.environ.get("ADSB_INGEST", "").strip().lower()
    if old:
        # Silently ignoring it would be worse than saying so, especially for
        # anyone who had it set to "chunks" and is now getting polling instead.
        print("note: ADSB_INGEST=%s is obsolete and ignored. There is one ingest "
              "path now: continuous polling of aircraft.json, filled in from "
              "history at startup. You can remove the setting." % old)
    if STORE_PATH:
        print("persistence: accumulating coverage in %s" % STORE_PATH)
        seed_data_dir()
    else:
        print("note: no ADSB_DATA_DIR, so coverage is kept in memory only and is "
              "lost on restart")
    cf = cities_file()
    if cf:
        print("cities: %s" % cf)
    try:
        rlat, rlon = receiver()
        print("receiver: %.6f, %.6f" % (rlat, rlon))
    except Exception as e:
        print("warning: could not read receiver.json yet (%s)" % e)
    POLLER.start()
    signal.signal(signal.SIGTERM, _on_term)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("listening on http://0.0.0.0:%d/  (view at /)" % PORT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        try:
            if not POLLER.stop():   # quiesce ingest before the final write
                sys.stderr.write("poller did not stop in time; flushing anyway\n")
            n = POLLER.flush()    # don't drop the last batch on a clean stop
            if n:
                print("flushed %d pending cells" % n)
        except Exception as e:
            sys.stderr.write("final flush failed: %s\n" % e)
        print("\nbye")


if __name__ == "__main__":
    main()
