# ADSb-Vue — tiny zero-dependency image (Python stdlib only)
FROM python:3.12-alpine

WORKDIR /app
# The cities.local.json* glob always matches the committed .example (so the build
# never fails on a fresh clone) and also pulls in a real cities.local.json when
# one sits in the build context — that's how a deployment's own city labels get
# into the image. See "Customizing the map" in the README.
COPY server.py index.html adsbvue_favicon.png cities.local.json* ./

ENV ADSB_ULTRAFEEDER=http://127.0.0.1 \
    ADSB_PORT=24556

EXPOSE 24556

# Probe whichever port the server actually listens on. ADSB_PORT is set above as
# an image default, so a plain get('ADSB_PORT') would always win and a site that
# configured ADSB_WEB_PORT would have its healthcheck probing the wrong port,
# and under host networking that can mean probing a different container. Match
# server.py's precedence: ADSB_WEB_PORT first, then ADSB_PORT.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python3 -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+(os.environ.get('ADSB_WEB_PORT') or os.environ.get('ADSB_PORT','24556'))+'/health',timeout=4)" || exit 1

CMD ["python3", "-u", "server.py"]
