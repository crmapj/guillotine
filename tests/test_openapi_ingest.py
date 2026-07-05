from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from guillotine.ingest import load_openapi
from guillotine.ir import SafetyTier

FIXTURE = Path(__file__).parent / "fixtures" / "todo_openapi.yaml"


def test_load_openapi_builds_curated_ir() -> None:
    spec = load_openapi(FIXTURE)

    assert spec.title == "Acme Tasks"
    assert spec.package_name == "acme_tasks"
    assert [resource.name for resource in spec.resources] == ["tasks", "users"]

    tasks = next(resource for resource in spec.resources if resource.name == "tasks")
    assert [op.name for op in tasks.operations] == ["create", "delete", "get", "list"]
    delete = next(op for op in tasks.operations if op.name == "delete")
    assert delete.safety_tier is SafetyTier.DELETE

    list_tasks = next(op for op in tasks.operations if op.name == "list")
    status = next(param for param in list_tasks.parameters if param.name == "status")
    assert status.enum == ("open", "closed")
    assert status.annotation == "str"


def _single_op_spec(tmp_path: Path, body: str) -> Path:
    spec_path = tmp_path / "probe.yaml"
    spec_path.write_text(
        dedent(
            """
            openapi: 3.0.3
            info:
              title: Probe
              version: "1.0"
            paths:
            """
        )
        + body,
        encoding="utf-8",
    )
    return spec_path


def _tier_for(tmp_path: Path, body: str) -> SafetyTier:
    spec = load_openapi(_single_op_spec(tmp_path, body))
    return spec.resources[0].operations[0].safety_tier


def test_safety_tier_catches_destructive_verbs_beyond_delete(tmp_path: Path) -> None:
    body = """
              /things/{id}/wipe:
                post:
                  tags: [things]
                  operationId: wipeThing
                  summary: Wipe all data
                  parameters:
                    - {name: id, in: path, required: true, schema: {type: string}}
            """
    assert _tier_for(tmp_path, body) is SafetyTier.DELETE


def test_safety_tier_does_not_flag_substring_false_positives(tmp_path: Path) -> None:
    # "closet" must not read as "close"; "create" path is a plain write.
    body = """
              /things/closet:
                post:
                  tags: [things]
                  operationId: addToCloset
                  summary: Add an item to the closet
            """
    assert _tier_for(tmp_path, body) is SafetyTier.WRITE


def test_safety_tier_honors_operation_override(tmp_path: Path) -> None:
    body = """
              /things/{id}:
                delete:
                  tags: [things]
                  operationId: deleteThing
                  x-guillotine-safety-tier: read
                  parameters:
                    - {name: id, in: path, required: true, schema: {type: string}}
            """
    assert _tier_for(tmp_path, body) is SafetyTier.READ


def test_load_openapi_accepts_yaml_in_a_json_named_file(tmp_path: Path) -> None:
    # Specs in the wild are often YAML with a .json extension; load them anyway.
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        dedent(
            """
            openapi: 3.0.3
            info:
              title: Mislabeled
              version: "1.0"
            paths:
              /things:
                get:
                  tags: [things]
                  operationId: listThings
            """
        ),
        encoding="utf-8",
    )
    assert load_openapi(spec_path).title == "Mislabeled"


def test_request_body_fields_are_extracted_with_enums(tmp_path: Path) -> None:
    body = """
              /widgets:
                post:
                  tags: [widgets]
                  operationId: createWidget
                  requestBody:
                    content:
                      application/json:
                        schema:
                          type: object
                          required: [name]
                          properties:
                            name: {type: string}
                            mode: {type: string, enum: [a, b]}
            """
    spec = load_openapi(_single_op_spec(tmp_path, body))
    fields = {f.name: f for f in spec.resources[0].operations[0].request_body.fields}
    assert fields["mode"].enum == ("a", "b")
    assert fields["name"].required is True


def test_response_shape_detects_wrapped_collection_and_object(tmp_path: Path) -> None:
    body = """
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
                              items: {type: array, items: {type: object}}
            """
    op = load_openapi(_single_op_spec(tmp_path, body)).resources[0].operations[0]
    assert op.list_key == "items"
    assert op.scalar_result is False


def test_page_only_query_is_not_treated_as_paginated(tmp_path: Path) -> None:
    body = """
              /items:
                get:
                  tags: [items]
                  operationId: listItems
                  parameters:
                    - {name: page, in: query, schema: {type: integer}}
            """
    spec = load_openapi(_single_op_spec(tmp_path, body))
    assert spec.resources[0].operations[0].pagination == {}


def test_untagged_versioned_paths_group_by_resource_segment(tmp_path: Path) -> None:
    body = """
              /v1/customers:
                get:
                  operationId: listCustomers
              /v1/charges:
                get:
                  operationId: listCharges
            """
    spec = load_openapi(_single_op_spec(tmp_path, body))
    names = sorted(resource.name for resource in spec.resources)
    assert names == ["charges", "customers"]


def test_load_openapi_resolves_schema_ref_enums(tmp_path: Path) -> None:
    spec_path = tmp_path / "ref_enum.yaml"
    spec_path.write_text(
        dedent(
            """
            openapi: 3.0.3
            info:
              title: Ref Enum
              version: "1.0"
            components:
              schemas:
                Status:
                  type: string
                  enum: [open, closed]
            paths:
              /tasks:
                get:
                  tags: [tasks]
                  operationId: listTasks
                  parameters:
                    - name: status
                      in: query
                      schema:
                        $ref: "#/components/schemas/Status"
            """
        ),
        encoding="utf-8",
    )

    spec = load_openapi(spec_path)

    status = spec.resources[0].operations[0].parameters[0]
    assert status.enum == ("open", "closed")


def test_required_body_fields_survive_the_truncation_cap(tmp_path: Path) -> None:
    # ~30 optional fields listed first, required fields last (Adyen POST /payments
    # shape). Required-first ordering must keep the required fields in the IR even
    # after the body-field cap, so they are never invisible to help_json.
    optional_props = "\n".join(
        f"                            opt_{i}: {{type: string}}" for i in range(30)
    )
    body = f"""
              /payments:
                post:
                  tags: [payments]
                  operationId: createPayment
                  requestBody:
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
    spec = load_openapi(_single_op_spec(tmp_path, body))
    fields = {f.name: f for f in spec.resources[0].operations[0].request_body.fields}
    assert "reference" in fields
    assert "return_url" in fields
    assert fields["reference"].required is True
    assert fields["return_url"].required is True


def test_server_url_template_variables_are_expanded(tmp_path: Path) -> None:
    spec_path = tmp_path / "servers.yaml"
    spec_path.write_text(
        dedent(
            """
            openapi: 3.0.3
            info:
              title: Templated
              version: "1.0"
            servers:
              - url: "https://{region}.api.example.com{basePath}"
                variables:
                  region: {default: "eu"}
                  basePath: {default: "/v2"}
            paths:
              /things:
                get:
                  tags: [things]
                  operationId: listThings
            """
        ),
        encoding="utf-8",
    )
    spec = load_openapi(spec_path)
    assert spec.default_server == "https://eu.api.example.com/v2"


def test_read_named_post_is_not_flagged_destructive(tmp_path: Path) -> None:
    # Plaid's Transfer product: a POST named `bank_transfer_balance_get` is a read
    # despite the `transfer` noun. It must not demand yes=True.
    body = """
              /bank_transfer/balance/get:
                post:
                  tags: [transfer]
                  operationId: bankTransferBalanceGet
                  summary: Get a bank transfer balance
            """
    assert _tier_for(tmp_path, body) is SafetyTier.WRITE


def test_description_only_soft_term_does_not_flag_destructive(tmp_path: Path) -> None:
    # `transactions_sync`: a read whose description mentions "removed" must not be
    # flagged. It is both read-named and only soft terms appear in prose.
    body = """
              /transactions/sync:
                post:
                  tags: [transactions]
                  operationId: transactionsSync
                  summary: Get incremental transaction updates
                  description: Returns added, modified, and removed transactions.
            """
    assert _tier_for(tmp_path, body) is SafetyTier.WRITE


def test_destructive_named_post_is_still_guarded(tmp_path: Path) -> None:
    body = """
              /transfers/cancel:
                post:
                  tags: [transfers]
                  operationId: cancelTransfer
                  summary: Cancel a transfer
            """
    assert _tier_for(tmp_path, body) is SafetyTier.DELETE


def test_delete_method_is_guarded_regardless_of_name(tmp_path: Path) -> None:
    body = """
              /things/{id}:
                delete:
                  tags: [things]
                  operationId: thingGet
                  summary: Retrieve
                  parameters:
                    - {name: id, in: path, required: true, schema: {type: string}}
            """
    assert _tier_for(tmp_path, body) is SafetyTier.DELETE


def test_swagger_2_document_is_rejected_with_a_clear_message(tmp_path: Path) -> None:
    spec_path = tmp_path / "swagger.json"
    spec_path.write_text(
        dedent(
            """
            {
              "swagger": "2.0",
              "info": {"title": "Old", "version": "1.0"},
              "paths": {}
            }
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"swagger='2.0'.*not supported"):
        load_openapi(spec_path)


def test_load_openapi_resolves_chained_schema_refs(tmp_path: Path) -> None:
    # A -> B -> concrete enum schema: all hops must resolve, or the enum guard and
    # annotation silently degrade to str.
    spec_path = tmp_path / "chained_ref.yaml"
    spec_path.write_text(
        dedent(
            """
            openapi: 3.0.3
            info:
              title: Chained Ref
              version: "1.0"
            components:
              schemas:
                StatusAlias:
                  $ref: "#/components/schemas/Status"
                Status:
                  type: string
                  enum: [open, closed]
            paths:
              /tasks:
                get:
                  tags: [tasks]
                  operationId: listTasks
                  parameters:
                    - name: status
                      in: query
                      schema:
                        $ref: "#/components/schemas/StatusAlias"
            """
        ),
        encoding="utf-8",
    )

    spec = load_openapi(spec_path)

    status = spec.resources[0].operations[0].parameters[0]
    assert status.enum == ("open", "closed")
    assert status.annotation == "str"
