from fastapi import HTTPException, Request


def require_laptop(request: Request):
    client = request.client.host if request.client else None
    hosts = {"localhost", "127.0.0.1", "::1"}
    if client == "testclient":
        hosts.add("testserver")
    if client not in {"127.0.0.1", "::1", "testclient"} or request.url.hostname not in hosts:
        raise HTTPException(403, "Use the laptop's localhost page for these controls.")
