"""API adapter shared by MCP and the reference tool loop."""

from urllib.parse import quote

import httpx


class AccessError(RuntimeError):
    pass


class AccessClient:
    def __init__(self, api_url, workspace, revision=None, *, transport=None):
        self.client = httpx.Client(base_url=api_url.rstrip("/") + "/", timeout=30,
                                   transport=transport)
        self.path = "v1/workspaces/" + quote(workspace, safe="") + "/ai/"
        self.revision = revision

    def close(self):
        self.client.close()

    def _request(self, method, endpoint, **kwargs):
        params = {"revision_id": self.revision} if self.revision else {}
        try:
            response = self.client.request(method, self.path + endpoint, params=params, **kwargs)
            if response.is_error:
                # Do not reflect untrusted bodies, URLs or credentials into protocol errors.
                raise AccessError(f"Docgrain read failed (HTTP {response.status_code})")
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AccessError("Docgrain read unavailable or invalid") from exc

    def specs(self):
        result = self._request("GET", "tools")
        # Pin subsequent calls so schema and results cannot drift during publication.
        self.revision = result["revision_id"]
        return result

    def call(self, name, arguments):
        if self.revision is None:
            self.specs()
        return self._request("POST", "call", json={"name": name, "arguments": arguments})
