import os, json, logging, requests
import azure.functions as func

# New Python model entry
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

UPSTREAM = os.environ.get("UPSTREAM_BASE_URL", "").rstrip("/")   # e.g. https://api.escuelajs.co/api/v1
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")           # CORS

def _cors(extra=None):
    h = {
        "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
        "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Vary": "Origin"
    }
    if extra: h.update(extra)
    return h

def _proxy(method, url, *, params=None, body=None, ctype=None, timeout=12):
    try:
        if method == "GET":
            r = requests.get(url, params=params, timeout=timeout)
        elif method == "POST":
            if ctype and "application/json" in ctype.lower():
                r = requests.post(url, params=params, json=body, timeout=timeout)
            else:
                r = requests.post(url, params=params, data=body, timeout=timeout)
        elif method == "PUT":
            if ctype and "application/json" in ctype.lower():
                r = requests.put(url, params=params, json=body, timeout=timeout)
            else:
                r = requests.put(url, params=params, data=body, timeout=timeout)
        else:
            return func.HttpResponse(
                json.dumps({"error": "method_not_allowed"}),
                status_code=405,
                headers=_cors({"Content-Type": "application/json"})
            )

        # Do not leak upstream headers; set a safe content type
        ct = r.headers.get("Content-Type", "application/json")
        return func.HttpResponse(body=r.content, status_code=r.status_code,
                                 headers=_cors({"Content-Type": ct}))
    except requests.RequestException:
        logging.exception("Upstream error")
        return func.HttpResponse(
            json.dumps({"error": "upstream_unavailable"}),
            status_code=502,
            headers=_cors({"Content-Type": "application/json"})
        )

@app.route(route="users/{id?}", methods=["GET", "POST", "PUT", "OPTIONS"])
def users(req: func.HttpRequest) -> func.HttpResponse:
    # Preflight CORS
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors())

    if not UPSTREAM:
        return func.HttpResponse(
            json.dumps({"error": "missing_upstream_config"}),
            status_code=500,
            headers=_cors({"Content-Type": "application/json"})
        )

    # Map:
    #   /api/users          ->  <UPSTREAM>/users
    #   /api/users/{id}     ->  <UPSTREAM>/users/{id}
    user_id = req.route_params.get("id")
    base = f"{UPSTREAM}/users"
    url = f"{base}/{user_id}" if user_id else base

    params = dict(req.params) if req.params else None
    ctype  = req.headers.get("Content-Type", "")
    body = None
    if req.method in ("POST", "PUT"):
        try:
            body = req.get_json()
        except ValueError:
            body = req.get_body()  # allow non-JSON bodies

    return _proxy(req.method, url, params=params, body=body, ctype=ctype)
