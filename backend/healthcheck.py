import sys
from urllib import request, error

URL = "http://127.0.0.1:8000/health"
TIMEOUT = 2

try:
    with request.urlopen(URL, timeout=TIMEOUT) as r:
        # 2xx is healthy
        if 200 <= r.status < 500:
            sys.exit(0)
        sys.exit(1)
except error.HTTPError as e:
    if e.code >= 200 and e.code <= 500:
        sys.exit(0)
    sys.exit(1)
except Exception:
    # Connection errors / timeouts -> unhealthy
    sys.exit(1)
