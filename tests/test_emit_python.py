from __future__ import annotations

import compileall
import importlib
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from textwrap import dedent

import pytest

from guillotine.build import build

FIXTURE = Path(__file__).parent / "fixtures" / "todo_openapi.yaml"


class FakeTransport:
    def __init__(self, status=200, data=None):
        self.status = status
        self.data = data if data is not None else [{"id": "t1", "status": "open"}]
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        from acme_tasks import Response

        return Response(self.status, {}, self.data, "")


class ModuleFakeTransport:
    def __init__(self, module, status=200, data=None):
        self.module = module
        self.status = status
        self.data = data if data is not None else []
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.module.Response(self.status, {}, self.data, "")


class PaginatedTransport:
    def __init__(self):
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        from acme_tasks import Response

        page = kwargs["query"].get("page", 1)
        data = [] if page >= 3 else [{"id": f"t{page}", "status": "open"}]
        return Response(200, {}, data, "")


class ShortPageTransport:
    """Page 1 is full (2 rows); page 2 is short (1 row) and must end the walk."""

    def __init__(self):
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        from acme_tasks import Response

        page = kwargs["query"].get("page", 1)
        data = [{"id": "a"}, {"id": "b"}] if page == 1 else [{"id": "c"}]
        return Response(200, {}, data, "")


def _import_generated(
    tmp_path: Path,
    *,
    fixture: Path = FIXTURE,
    package_name: str | None = None,
):
    build(
        FIXTURE if fixture is None else fixture,
        output_dir=tmp_path,
        package_name=package_name,
    )
    package = package_name or "acme_tasks"
    sys.path.insert(0, str(tmp_path))
    try:
        for key in list(sys.modules):
            if key == package or key.startswith(package + "."):
                sys.modules.pop(key, None)
        return importlib.import_module(package)
    finally:
        sys.path.remove(str(tmp_path))


def test_generated_dsl_runs_distilled_operation(tmp_path: Path) -> None:
    acme = _import_generated(tmp_path)
    transport = FakeTransport()
    c = acme.connect(transport=transport)

    rows = c.tasks.list(status="open", limit=5).head(2)

    assert rows == [{"id": "t1", "status": "open"}]
    assert transport.calls[0]["method"] == "GET"
    assert transport.calls[0]["path"] == "/tasks"
    assert transport.calls[0]["query"] == {"status": "open", "limit": 5}
    assert c.raw is transport


def test_generated_help_json_exposes_choices(tmp_path: Path) -> None:
    acme = _import_generated(tmp_path)

    help_data = acme.help_json("tasks.list")

    assert help_data["name"] == "list"
    assert help_data["choices"] == {"status": ["open", "closed"]}
    assert "status" in acme.cheatsheet(section="tasks", grep="list")


def test_generated_enum_guard_teaches_before_api_call(tmp_path: Path) -> None:
    acme = _import_generated(tmp_path)
    transport = FakeTransport()
    c = acme.connect(transport=transport)

    with pytest.raises(acme.ChoiceError, match="Unknown status='bad'"):
        c.tasks.list(status="bad")

    assert transport.calls == []


def test_generated_delete_requires_explicit_yes(tmp_path: Path) -> None:
    acme = _import_generated(tmp_path)
    transport = FakeTransport(data={"deleted": True})
    c = acme.connect(transport=transport)

    with pytest.raises(acme.SafetyBlocked, match="pass yes=True"):
        c.tasks.delete("t1").run()

    c.tasks.delete("t1", yes=True).run()
    assert transport.calls[0]["method"] == "DELETE"
    assert transport.calls[0]["path"] == "/tasks/t1"


def test_generated_pagination_all_distills_bounded_pages(tmp_path: Path) -> None:
    acme = _import_generated(tmp_path)
    transport = PaginatedTransport()
    c = acme.connect(transport=transport)

    rows = c.tasks.list(status="open").all(max_pages=5, per_page=1)

    assert rows == [
        {"id": "t1", "status": "open"},
        {"id": "t2", "status": "open"},
    ]
    assert [call["query"]["page"] for call in transport.calls] == [1, 2, 3]
    assert [call["query"]["per_page"] for call in transport.calls] == [1, 1, 1]


def test_generated_names_survive_parameter_and_class_collisions(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "collisions.yaml"
    fixture.write_text(
        dedent(
            """
            openapi: 3.0.3
            info:
              title: Collision Probe
              version: "1.0"
            servers:
              - url: https://api.example.test
            paths:
              /items:
                get:
                  tags: [client]
                  operationId: listItems
                  parameters:
                    - name: foo-bar
                      in: query
                      schema:
                        type: string
                    - name: foo_bar
                      in: query
                      schema:
                        type: string
              /raw:
                get:
                  tags: [raw]
                  operationId: raw
            """
        ),
        encoding="utf-8",
    )
    build(fixture, output_dir=tmp_path, package_name="collision_probe")

    assert compileall.compile_dir(str(tmp_path / "collision_probe"), quiet=1)
    mod = _import_generated(
        tmp_path,
        fixture=fixture,
        package_name="collision_probe",
    )

    assert mod.ClientResource.__name__ == "ClientResource"
    assert hasattr(mod.connect(), "client")
    assert hasattr(mod.connect(), "raw_resource")


def test_generated_api_key_header_auth_uses_openapi_scheme(tmp_path: Path) -> None:
    fixture = tmp_path / "apikey.yaml"
    fixture.write_text(
        dedent(
            """
            openapi: 3.0.3
            info:
              title: Api Key Probe
              version: "1.0"
            servers:
              - url: https://api.example.test
            components:
              securitySchemes:
                ApiKeyAuth:
                  type: apiKey
                  in: header
                  name: X-API-Key
            security:
              - ApiKeyAuth: []
            paths:
              /items:
                get:
                  tags: [items]
                  operationId: listItems
            """
        ),
        encoding="utf-8",
    )
    mod = _import_generated(tmp_path, fixture=fixture, package_name="api_key_probe")
    transport = ModuleFakeTransport(mod)

    mod.connect(token="sekret", transport=transport).items.list().run()

    assert transport.calls[0]["headers"] == {"X-API-Key": "sekret"}


def test_generated_dangerous_post_requires_yes(tmp_path: Path) -> None:
    fixture = tmp_path / "dangerous_post.yaml"
    fixture.write_text(
        dedent(
            """
            openapi: 3.0.3
            info:
              title: Dangerous Post
              version: "1.0"
            servers:
              - url: https://api.example.test
            paths:
              /repos/{owner}/{repo}/transfer:
                post:
                  tags: [repos]
                  operationId: transferRepo
                  summary: Transfer a repository
                  parameters:
                    - name: owner
                      in: path
                      required: true
                      schema:
                        type: string
                    - name: repo
                      in: path
                      required: true
                      schema:
                        type: string
                  requestBody:
                    required: true
                    content:
                      application/json:
                        schema:
                          type: object
            """
        ),
        encoding="utf-8",
    )
    mod = _import_generated(tmp_path, fixture=fixture, package_name="dangerous_post")
    transport = ModuleFakeTransport(mod, data={"ok": True})
    client = mod.connect(transport=transport)

    with pytest.raises(mod.SafetyBlocked, match="destructive"):
        client.repos.transfer("octocat", "Hello-World", body={}).run()

    client.repos.transfer("octocat", "Hello-World", body={}, yes=True).run()
    assert transport.calls[0]["method"] == "POST"


def test_generated_cascade_confirmation_must_match_target(tmp_path: Path) -> None:
    fixture = tmp_path / "cascade.yaml"
    fixture.write_text(
        dedent(
            """
            openapi: 3.0.3
            info:
              title: Cascade Probe
              version: "1.0"
            servers:
              - url: https://api.example.test
            paths:
              /repos/{owner}/{repo}:
                delete:
                  tags: [repos]
                  operationId: deleteRepo
                  summary: Recursively purge repository
                  parameters:
                    - name: owner
                      in: path
                      required: true
                      schema:
                        type: string
                    - name: repo
                      in: path
                      required: true
                      schema:
                        type: string
            """
        ),
        encoding="utf-8",
    )
    mod = _import_generated(tmp_path, fixture=fixture, package_name="cascade_probe")
    transport = ModuleFakeTransport(mod, data={"deleted": True})
    client = mod.connect(transport=transport)

    with pytest.raises(mod.SafetyBlocked, match="confirm_name='Hello-World'"):
        client.repos.delete(
            "octocat",
            "Hello-World",
            yes=True,
            confirm_name="wrong",
        ).run()

    client.repos.delete(
        "octocat",
        "Hello-World",
        yes=True,
        confirm_name="Hello-World",
    ).run()
    assert transport.calls[0]["method"] == "DELETE"


def test_distillation_signals_key_truncation(tmp_path: Path) -> None:
    acme = _import_generated(tmp_path)
    big = {f"k{i}": i for i in range(60)}
    c = acme.connect(transport=FakeTransport(data=big))

    row = c.tasks.get("t1").one()

    assert "__truncated_keys__" in row
    assert "10 more key" in row["__truncated_keys__"]


def test_head_reports_total_when_more_rows_exist(tmp_path: Path, capsys) -> None:
    acme = _import_generated(tmp_path)
    data = [{"id": f"t{i}"} for i in range(5)]
    c = acme.connect(transport=FakeTransport(data=data))

    rows = c.tasks.list(status="open").head(2)

    assert len(rows) == 2
    assert "2 of 5 row(s) shown" in capsys.readouterr().err


def test_all_infers_page_size_and_stops_on_short_page(tmp_path: Path) -> None:
    acme = _import_generated(tmp_path)
    transport = ShortPageTransport()
    c = acme.connect(transport=transport)

    # No per_page passed and the fixture's per_page has no default, so the page size
    # is unknown; .all() must infer it from page 1 and stop after the short page 2.
    rows = c.tasks.list(status="open").all(max_pages=5)

    assert [r["id"] for r in rows] == ["a", "b", "c"]
    assert len(transport.calls) == 2  # did not over-fetch a 3rd page


def test_array_param_default_is_not_a_mutable_literal(tmp_path: Path) -> None:
    fixture = tmp_path / "arr_default.yaml"
    fixture.write_text(
        dedent(
            """
            openapi: 3.0.3
            info:
              title: Arr Default
              version: "1.0"
            paths:
              /items:
                get:
                  tags: [items]
                  operationId: listItems
                  parameters:
                    - name: tags
                      in: query
                      schema:
                        type: array
                        default: [a, b]
            """
        ),
        encoding="utf-8",
    )
    build(fixture, output_dir=tmp_path, package_name="arr_default")

    src = (tmp_path / "arr_default" / "_client.py").read_text(encoding="utf-8")
    assert "= ['a', 'b']" not in src
    assert "tags: list | None = None" in src


def test_body_enum_is_exposed_in_help_and_guarded(tmp_path: Path) -> None:
    fixture = tmp_path / "body_enum.yaml"
    fixture.write_text(
        dedent(
            """
            openapi: 3.0.3
            info:
              title: Body Enum
              version: "1.0"
            servers:
              - url: https://api.example.test
            paths:
              /widgets:
                post:
                  tags: [widgets]
                  operationId: createWidget
                  requestBody:
                    required: true
                    content:
                      application/json:
                        schema:
                          type: object
                          required: [name]
                          properties:
                            name: {type: string}
                            status: {type: string, enum: [draft, final]}
            """
        ),
        encoding="utf-8",
    )
    mod = _import_generated(tmp_path, fixture=fixture, package_name="body_enum")

    body = {f["name"]: f for f in mod.help_json("widgets.create")["body"]}
    assert body["status"]["enum"] == ["draft", "final"]
    assert body["name"]["required"] is True

    transport = ModuleFakeTransport(mod, data={})
    c = mod.connect(transport=transport)
    with pytest.raises(mod.ChoiceError, match=r"body\['status'\]='bogus'"):
        c.widgets.create(body={"name": "x", "status": "bogus"})

    c.widgets.create(body={"name": "x", "status": "final"}).run()
    assert transport.calls[0]["method"] == "POST"


def test_required_body_fields_appear_in_docstring_despite_cap(tmp_path: Path) -> None:
    # 30 optional fields listed first, then required fields last (Adyen shape). The
    # docstring cap must not bury the required fields behind the "... N more" marker.
    optional_props = "\n".join(
        f"                            opt_{i}: {{type: string}}" for i in range(30)
    )
    fixture = tmp_path / "late_required.yaml"
    fixture.write_text(
        dedent(
            f"""
            openapi: 3.0.3
            info:
              title: Late Required
              version: "1.0"
            servers:
              - url: https://api.example.test
            paths:
              /payments:
                post:
                  tags: [payments]
                  operationId: createPayment
                  requestBody:
                    required: true
                    content:
                      application/json:
                        schema:
                          type: object
                          required: [reference, return_url]
                          properties:
{optional_props}
                            reference: {{type: string}}
                            return_url: {{type: string}}
            """
        ),
        encoding="utf-8",
    )
    mod = _import_generated(tmp_path, fixture=fixture, package_name="late_required")

    doc = mod.help_json("payments.create")["doc"]
    assert "reference (str, required)" in doc
    assert "return_url (str, required)" in doc


def test_response_shape_unwraps_collection_and_keeps_object(tmp_path: Path) -> None:
    fixture = tmp_path / "shapes.yaml"
    fixture.write_text(
        dedent(
            """
            openapi: 3.0.3
            info:
              title: Shapes
              version: "1.0"
            servers:
              - url: https://api.example.test
            paths:
              /search:
                get:
                  tags: [search]
                  operationId: runSearch
                  responses:
                    "200":
                      content:
                        application/json:
                          schema:
                            type: object
                            properties:
                              total: {type: integer}
                              items: {type: array, items: {type: object}}
              /things/{id}:
                get:
                  tags: [things]
                  operationId: getThing
                  parameters:
                    - {name: id, in: path, required: true, schema: {type: string}}
                  responses:
                    "200":
                      content:
                        application/json:
                          schema:
                            type: object
                            properties:
                              id: {type: string}
                              tags: {type: array, items: {type: string}}
            """
        ),
        encoding="utf-8",
    )
    mod = _import_generated(tmp_path, fixture=fixture, package_name="shapes")

    # Wrapped collection: .head() unwraps the spec-named "items" array.
    c = mod.connect(
        transport=ModuleFakeTransport(
            mod, data={"total": 2, "items": [{"id": "a"}, {"id": "b"}]}
        )
    )
    assert [r["id"] for r in c.search.run().head(5)] == ["a", "b"]

    # Single object that happens to have an array field: .one() must not unwrap it.
    c2 = mod.connect(
        transport=ModuleFakeTransport(mod, data={"id": "x", "tags": ["p", "q"]})
    )
    assert c2.things.get("x").one()["id"] == "x"


def test_distills_geojson_feature_collection(tmp_path: Path) -> None:
    acme = _import_generated(tmp_path)
    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {"id": "a", "properties": {"event": "Tornado Warning"}},
            {"id": "b", "properties": {"event": "Flood Watch"}},
        ],
        "title": "alerts",
    }
    c = acme.connect(transport=FakeTransport(data=feature_collection))

    rows = c.tasks.list(status="open").head(5)

    # The agent must get the 2 features, not the FeatureCollection envelope.
    assert [r["id"] for r in rows] == ["a", "b"]


def test_array_enum_param_is_guarded_elementwise(tmp_path: Path) -> None:
    fixture = tmp_path / "array_enum.yaml"
    fixture.write_text(
        dedent(
            """
            openapi: 3.0.3
            info:
              title: Array Enum
              version: "1.0"
            servers:
              - url: https://api.example.test
            paths:
              /things:
                get:
                  tags: [things]
                  operationId: listThings
                  parameters:
                    - name: severity
                      in: query
                      schema:
                        type: array
                        items:
                          type: string
                          enum: [low, high]
            """
        ),
        encoding="utf-8",
    )
    mod = _import_generated(tmp_path, fixture=fixture, package_name="array_enum")

    assert mod.help_json("things.list")["choices"]["severity"] == ["low", "high"]

    transport = ModuleFakeTransport(mod, data=[])
    c = mod.connect(transport=transport)
    with pytest.raises(mod.ChoiceError, match="Unknown severity='bogus'"):
        c.things.list(severity=["low", "bogus"])

    c.things.list(severity=["low", "high"]).run()
    assert transport.calls[0]["query"]["severity"] == ["low", "high"]


def test_generated_transport_rejects_non_http_scheme(tmp_path: Path) -> None:
    acme = _import_generated(tmp_path)
    transport = acme.connect().raw

    with pytest.raises(acme.GuillotineError, match="non-HTTP"):
        transport.request(
            method="GET",
            base_url="file:///etc",
            path="/passwd",
            query={},
            headers={},
            body=None,
            content_type="application/json",
            timeout=5,
        )


def test_generated_transport_rejects_multipart_body(tmp_path: Path) -> None:
    acme = _import_generated(tmp_path)
    transport = acme.connect().raw

    with pytest.raises(acme.GuillotineError, match="multipart"):
        transport.request(
            method="POST",
            base_url="https://api.example.test",
            path="/upload",
            query={},
            headers={},
            body={"file": "data"},
            content_type="multipart/form-data",
            timeout=5,
        )


def test_generated_transport_form_encodes_urlencoded_body(tmp_path: Path) -> None:
    received: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            received["body"] = self.rfile.read(length).decode()
            received["ctype"] = self.headers.get("Content-Type", "")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, fmt, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        acme = _import_generated(tmp_path)
        transport = acme.connect().raw
        transport.request(
            method="POST",
            base_url=f"http://127.0.0.1:{server.server_port}",
            path="/x",
            query={},
            headers={},
            body={"a": "1", "b": "two"},
            content_type="application/x-www-form-urlencoded",
            timeout=5,
        )
    finally:
        server.shutdown()

    assert received["body"] == "a=1&b=two"
    assert received["ctype"] == "application/x-www-form-urlencoded"


def test_generated_http_error_raises_api_error(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"missing"}')

        def log_message(self, fmt, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        acme = _import_generated(tmp_path)
        client = acme.connect(base_url=f"http://127.0.0.1:{server.server_port}")

        with pytest.raises(acme.ApiError, match="HTTP 404"):
            client.tasks.get("missing").one()
    finally:
        server.shutdown()


def test_generated_skill_names_match_agent_skills_spec(tmp_path: Path) -> None:
    # package_name "acme_tasks" has underscores; every SKILL.md name must be a valid
    # Agent Skills slug: ^[a-z0-9]+(-[a-z0-9]+)*$.
    build(FIXTURE, output_dir=tmp_path)
    name_re = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

    skill_files = list((tmp_path / "skills").rglob("SKILL.md"))
    assert skill_files

    for skill in skill_files:
        text = skill.read_text(encoding="utf-8")
        match = re.search(r"^name:\s*(\S+)\s*$", text, re.MULTILINE)
        assert match, f"no name in {skill}"
        name = match.group(1)
        assert name_re.match(name), f"invalid skill name {name!r} in {skill}"
        assert "_" not in name
