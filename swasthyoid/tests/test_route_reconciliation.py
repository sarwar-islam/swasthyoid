"""B8a: every FastAPI route against the web mock, from the app's own OpenAPI specification. A new route on either side
must be explained (devtools/routes.py) and docs/ROUTES.md regenerated."""
from swasthyoid.devtools import routes


def test_every_route_difference_is_known_and_explained():
    server, mock = routes.server_routes(), routes.mock_routes()
    assert mock - server == set(routes.UNBUILT)  # the screens with no server route yet (M5, M7, M8, M13)
    assert server - mock == set(routes.SERVER_ONLY)
    assert ("GET", "/health") in server & mock
    assert len(server) == 65 and len(mock) == 70 and len(server & mock) == 63


def test_the_route_report_is_current():
    assert routes.REPORT.read_text(encoding="utf-8") == routes.report(), "run: python -m swasthyoid.devtools.routes"


def test_the_mock_parser_reads_list_built_routes():
    src = 'x ...(["approve", "decline"] as const).map((verb): [Method, string, Handler] => ["POST", `/a/{id}/${verb}`, ' \
          '(r) => 1]) ["GET", "/b/{id}", (r) => 1] ...(["/v", "/v/{id}/c"] as const).map((path): X => ["POST", path, y])'
    assert routes.mock_routes(src) == {("POST", "/a/{}/approve"), ("POST", "/a/{}/decline"), ("GET", "/b/{}"),
                                       ("POST", "/v"), ("POST", "/v/{}/c")}
