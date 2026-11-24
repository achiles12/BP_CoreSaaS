"""B07 test helpers: custom roles and rows inserted straight into a tenant schema."""

import uuid

from tests.b04_helpers import B04_PW, add_member, sql, unique_email  # noqa: F401


def member_with_perms(
    url: str, slug: str, role_key: str, perms: list[str]
) -> tuple[uuid.UUID, str]:
    """A fresh member whose only role grants exactly `perms` (role created once)."""
    s = f'"tenant_{slug}"'
    sql(
        url,
        f"insert into {s}.roles (key, name, priority, landing_path) "  # noqa: S608
        "values ($1, $1, 60, '/home/user') on conflict (key) do nothing",
        role_key,
    )
    sql(
        url,
        f"insert into {s}.role_permissions (role_id, permission_id) "  # noqa: S608
        f"select r.id, p.id from {s}.roles r, {s}.permissions p "
        "where r.key = $1 and p.key = any($2::text[]) on conflict do nothing",
        role_key,
        perms,
    )
    return add_member(url, slug, role_key, unique_email(role_key))


def user_id(url: str, email: str) -> uuid.UUID:
    return sql(url, "select id from users where email=$1", email)[0]["id"]


def insert_file(
    url: str, slug: str, owner: uuid.UUID, name: str, status: str = "active", size: int = 10
) -> uuid.UUID:
    return sql(
        url,
        f'insert into "tenant_{slug}".files '  # noqa: S608
        "(name, mime_type, size_bytes, object_key, uploaded_by, status) "
        "values ($1, 'text/plain', $2, $3, $4, $5) returning id",
        name,
        size,
        f"test/{uuid.uuid4()}",
        owner,
        status,
    )[0]["id"]


def insert_item(
    url: str,
    slug: str,
    owner: uuid.UUID,
    title: str,
    description: str | None = None,
    status: str = "open",
    deleted: bool = False,
) -> uuid.UUID:
    return sql(
        url,
        f'insert into "tenant_{slug}"._template_items '  # noqa: S608
        "(title, description, status, owner_id, deleted_at) "
        "values ($1, $2, $3, $4, case when $5 then now() end) returning id",
        title,
        description,
        status,
        owner,
        deleted,
    )[0]["id"]


def drop_test_roles(url: str, slug: str, prefix: str = "b7_") -> None:
    """Remove roles made by member_with_perms (grants + assignments cascade).

    The B04 world is shared by every test module; a leftover role would show
    up in other tests' role lists.
    """
    sql(url, f'delete from "tenant_{slug}".roles where key like $1', prefix + "%")  # noqa: S608
