# ADSb-Vue — tiny zero-dependency image (Python stdlib only)
FROM python:3.12-alpine

WORKDIR /app
# The cities.local.json* glob always matches the committed .example (so the build
# never fails on a fresh clone) and also pulls in a real cities.local.json when
# one sits in the build context — that's how a deployment's own city labels get
# into the image. See "Customizing the map" in the README.
COPY server.py index.html adsbvue_favicon.png cities.local.json* ./

ENV ADSB_ULTRAFEEDER=http://127.0.0.1

EXPOSE 24556

# Deliberately NO port set here. server.py accepts either ADSB_WEB_PORT or the
# older ADSB_PORT and defaults to 24556 on its own, so an image-level default
# buys nothing and actively hurts: whichever name the image pinned would outrank
# the other one set by the user, and their server would listen somewhere they
# did not ask for. Leaving both unset means the user's choice always wins.
#
# The healthcheck follows the same precedence as server.py so it always probes
# the port actually being listened on. Getting this wrong is quiet and nasty:
# under host networking a mismatched probe can hit a different container
# entirely and report healthy.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python3 -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+(os.environ.get('ADSB_WEB_PORT') or os.environ.get('ADSB_PORT','24556'))+'/health',timeout=4)" || exit 1

CMD ["python3", "-u", "server.py"]
