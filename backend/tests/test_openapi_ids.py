"""B08 D14/D15: operationIds are route names, unique, and the dump is stable."""

from app.openapi_dump import build_schema, main


def test_operation_ids_are_route_names_and_unique() -> None:
    schema = build_schema()  # raises on duplicates
    ops = {
        (method, path): op["operationId"]
        for path, item in schema["paths"].items()
        for method, op in item.items()
    }
    assert ops[("get", "/me")] == "me"
    assert ops[("post", "/auth/login")] == "login"
    assert ops[("post", "/auth/refresh")] == "refresh"


def test_dump_is_deterministic(tmp_path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert main(["x", str(a)]) == 0
    assert main(["x", str(b)]) == 0
    assert a.read_text() == b.read_text()
    assert a.read_text().endswith("\n")
