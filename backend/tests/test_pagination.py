"""B06: sort/filter parser (design §3.1, D6–D8; plan review focus 1–3). Unit, no DB."""

import uuid

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, Table, Text
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

from app.core.errors import ValidationFailed
from app.core.pagination import (
    MAX_SORT_FIELDS,
    FilterField,
    ListSpec,
    openapi_params,
    parse_filters,
    parse_sort,
)

t = Table(
    "things",
    MetaData(),
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("name", Text),
    Column("status", Text),
    Column("size", Integer),
    Column("owner_id", UUID(as_uuid=True)),
    Column("created_at", DateTime(timezone=True)),
)

SPEC = ListSpec(
    sort={"name": t.c.name, "created_at": t.c.created_at, "size": t.c.size, "status": t.c.status},
    default_sort="-created_at",
    filters={
        "status": FilterField(t.c.status, "enum", choices=("open", "done")),
        "name": FilterField(t.c.name, "text"),
        "owner_id": FilterField(t.c.owner_id, "uuid"),
        "size": FilterField(t.c.size, "int", ranges=True),
        "created_at": FilterField(t.c.created_at, "datetime", ranges=True),
    },
)


def sql(clauses: list) -> list[str]:
    return [
        str(c.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for c in clauses
    ]


def err_fields(exc: pytest.ExceptionInfo[ValidationFailed]) -> str:
    return str(exc.value.message) + str(exc.value.fields)


# ----------------------------------------------------------------- sort ---- #
def test_sort_two_fields_plus_id_tiebreak() -> None:
    assert sql(parse_sort(SPEC, "-created_at,name", t.c.id)) == [
        "things.created_at DESC",
        "things.name ASC",
        "things.id ASC",
    ]


@pytest.mark.parametrize("raw", [None, "", " ", ","])
def test_sort_empty_uses_default(raw: str | None) -> None:
    assert sql(parse_sort(SPEC, raw, t.c.id)) == ["things.created_at DESC", "things.id ASC"]


def test_sort_unknown_field_lists_allowed() -> None:
    with pytest.raises(ValidationFailed) as e:
        parse_sort(SPEC, "-password", t.c.id)
    assert "password" in err_fields(e) and "created_at" in err_fields(e)


def test_sort_too_many_fields() -> None:
    assert MAX_SORT_FIELDS == 3
    with pytest.raises(ValidationFailed):
        parse_sort(SPEC, "name,size,status,created_at", t.c.id)


def test_sort_duplicate_field_is_422() -> None:
    with pytest.raises(ValidationFailed):
        parse_sort(SPEC, "name,-name", t.c.id)


# --------------------------------------------------------------- filter ---- #
def test_filter_equals_and_in_list() -> None:
    assert sql(parse_filters(SPEC, {"filter[status]": "open"})) == ["things.status = 'open'"]
    assert sql(parse_filters(SPEC, {"filter[status]": "open,done"})) == [
        "things.status IN ('open', 'done')"
    ]


def test_filter_and_combines() -> None:
    assert len(parse_filters(SPEC, {"filter[status]": "open", "filter[name]": "x"})) == 2


@pytest.mark.parametrize("value", ["", " ", ","])
def test_filter_empty_value_ignored(value: str) -> None:
    assert parse_filters(SPEC, {"filter[status]": value}) == []


@pytest.mark.parametrize(
    "raw",
    [
        {"filter[status]": "bogus"},
        {"filter[owner_id]": "not-a-uuid"},
        {"filter[size]": "ten"},
        {"filter[created_at][gte]": "yesterday"},
        {"filter[password]": "x"},
        {"filter[status": "open"},
        {"filter[size][like]": "1"},
        {"filter[status][gte]": "open"},  # ranges only where allowed
        {"filters[status]": "open"},
    ],
)
def test_filter_bad_input_is_422(raw: dict[str, str]) -> None:
    with pytest.raises(ValidationFailed):
        parse_filters(SPEC, raw)


def test_filter_uuid_and_int() -> None:
    u = uuid.UUID("11111111-1111-1111-1111-111111111111")
    assert sql(parse_filters(SPEC, {"filter[owner_id]": str(u)})) == [f"things.owner_id = '{u}'"]
    assert sql(parse_filters(SPEC, {"filter[size][gte]": "10", "filter[size][lte]": "20"})) == [
        "things.size >= 10",
        "things.size <= 20",
    ]


def test_filter_date_ranges_include_whole_day() -> None:
    out = sql(
        parse_filters(
            SPEC, {"filter[created_at][gte]": "2026-11-19", "filter[created_at][lte]": "2026-11-19"}
        )
    )
    assert out[0] == "things.created_at >= '2026-11-19 00:00:00+00:00'"
    # date-only upper bound means "up to the end of that day"
    assert out[1] == "things.created_at < '2026-11-20 00:00:00+00:00'"


def test_filter_datetime_with_offset() -> None:
    out = sql(parse_filters(SPEC, {"filter[created_at][lte]": "2026-11-19T18:30:00+08:00"}))
    assert out == ["things.created_at <= '2026-11-19 18:30:00+08:00'"]
    out = sql(parse_filters(SPEC, {"filter[created_at][gte]": "2026-11-19T10:00:00Z"}))
    assert out == ["things.created_at >= '2026-11-19 10:00:00+00:00'"]


def test_non_filter_params_are_not_my_business() -> None:
    assert parse_filters(SPEC, {"page": "2", "q": "x", "sort": "name"}) == []


# -------------------------------------------------------------- openapi ---- #
def test_openapi_params() -> None:
    params = {p["name"]: p for p in openapi_params(SPEC)["parameters"]}
    assert {"sort", "filter[status]", "filter[size][gte]", "filter[created_at][lte]"} <= set(params)
    assert "filter[status][gte]" not in params
    assert params["filter[status]"]["in"] == "query"
    assert "-created_at" in params["sort"]["description"]
