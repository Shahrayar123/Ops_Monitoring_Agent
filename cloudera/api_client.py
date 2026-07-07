"""Client for the Cloudera Manager REST API.

Cloudera Manager (CM) is the admin console of a Cloudera cluster. It exposes a
REST API at https://<host>:<port>/api/<version>/... and uses the same username/
password as the CM web page (HTTP Basic auth).

This client covers only the six calls this product needs:

    resolve_version()   -> which API version the cluster speaks (asked once)
    get_hosts()         -> every machine in the cluster + its health
    get_services()      -> every service (HDFS, YARN, ...) + its health
    get_roles()         -> the parts of one service (NameNode, DataNode, ...)
    query_metrics()     -> numbers over time (CPU %, memory, disk, ...)
    get_events()        -> alert/warning events raised by the cluster

The API version is never hard-coded: the cluster tells us via GET /api/version.

`transport` exists so tests can plug in a fake HTTP layer — there is no real
cluster available to test against yet.
"""

from typing import Optional

import httpx


class ClouderaApiError(Exception):
    """The Cloudera Manager API answered with an error (bad credentials, bad
    URL, server problem, ...)."""


class ClouderaApiClient:
    def __init__(
        self,
        cm_host: str,
        port: int,
        username: str,
        password: str,
        use_tls: bool = True,
        tls_cert_path: Optional[str] = None,
        api_version: str = "auto",
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        scheme = "https" if use_tls else "http"
        self._base_url = f"{scheme}://{cm_host}:{port}"

        # "auto" means: ask the cluster for its version on first use.
        self._api_version: Optional[str] = None if api_version == "auto" else api_version

        verify = tls_cert_path if (use_tls and tls_cert_path) else use_tls
        self._http = httpx.Client(
            auth=(username, password),
            verify=verify,
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ClouderaApiClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ---------- the six API calls ----------

    def resolve_version(self) -> str:
        """Ask the cluster which API version it speaks, e.g. "v51"."""
        response = self._http.get(f"{self._base_url}/api/version")
        if response.is_error:
            raise ClouderaApiError(
                f"GET /api/version failed: {response.status_code} {response.text}"
            )
        return response.text.strip()

    def get_hosts(self) -> dict:
        return self._get("/hosts", params={"view": "full"})

    def get_services(self, cluster_name: str) -> dict:
        return self._get(f"/clusters/{cluster_name}/services", params={"view": "full"})

    def get_roles(self, cluster_name: str, service_name: str) -> dict:
        return self._get(
            f"/clusters/{cluster_name}/services/{service_name}/roles",
            params={"view": "full"},
        )

    def query_metrics(
        self,
        query: str,
        from_time: Optional[str] = None,
        to_time: str = "now",
        desired_rollup: str = "HOURLY",
    ) -> dict:
        """Fetch numeric metrics. `query` is a CM "tsquery" string — build it
        with cloudera.metric_query.build_metric_query().

        from_time/to_time are ISO timestamps (to_time defaults to "now"). We ask
        for HOURLY rollup, matching how the data was exported for the demo, so
        one point per hour rather than per-second raw samples."""
        params = {
            "query": query,
            "contentType": "application/json",
            "desiredRollup": desired_rollup,
            "mustUseDesiredRollup": "true",
            "to": to_time,
        }
        if from_time:
            params["from"] = from_time
        return self._get("/timeseries", params=params)

    def get_events(self, query: str) -> dict:
        return self._get("/events", params={"query": query})

    # ---------- internals ----------

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        if self._api_version is None:
            self._api_version = self.resolve_version()
        url = f"{self._base_url}/api/{self._api_version}{path}"
        response = self._http.get(url, params=params)
        if response.is_error:
            raise ClouderaApiError(
                f"GET {path} failed: {response.status_code} {response.text}"
            )
        return response.json()
