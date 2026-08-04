"""auth tables and user scoping

Revision ID: f9fc01e849ec
Revises: 60d8ab46909b
Create Date: 2026-08-04 12:59:20.203665

"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f9fc01e849ec"
down_revision: Union[str, Sequence[str], None] = "60d8ab46909b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sessions_valid_after",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "users_email_lower_idx", "users", [sa.text("lower(email)")], unique=True
    )

    op.create_table(
        "accounts",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_account_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "provider_account_id", name="accounts_provider_account_uq"
        ),
    )
    op.create_index("accounts_user_id_idx", "accounts", ["user_id"])

    op.create_table(
        "email_tokens",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose IN ('verify_email', 'reset_password')",
            name="email_tokens_purpose_check",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "email_tokens_user_purpose_idx", "email_tokens", ["user_id", "purpose"]
    )

    # ── Backfill: assign the pre-auth corpus to a bootstrap user ──────────
    # Runs while user_id is still nullable and RLS doesn't exist (slice 2),
    # so nothing can interfere. Wiping instead of assigning would burn real
    # Voyage credits on re-embedding — preservation is deliberate.
    conn = op.get_bind()
    legacy = conn.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM conversations WHERE user_id IS NULL)"
            " + (SELECT count(*) FROM documents WHERE user_id IS NULL)"
            " + (SELECT count(*) FROM chunks WHERE user_id IS NULL)"
        )
    ).scalar_one()
    if legacy:
        email = os.environ.get("BOOTSTRAP_USER_EMAIL", "").strip().lower()
        if not email:
            raise RuntimeError(
                "existing rows have no owner: set BOOTSTRAP_USER_EMAIL=<your email> "
                "(e.g. in .env) and re-run `make migrate` — the legacy corpus will "
                "be assigned to that user"
            )
        bootstrap_id = conn.execute(
            sa.text("INSERT INTO users (email) VALUES (:email) RETURNING id"),
            {"email": email},
        ).scalar_one()
        for table in ("conversations", "documents", "chunks"):
            conn.execute(
                sa.text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"),  # noqa: S608 — table names from a literal tuple
                {"uid": bootstrap_id},
            )

    for table in ("conversations", "documents", "chunks"):
        op.alter_column(table, "user_id", nullable=False)
        op.create_foreign_key(
            f"{table}_user_id_fkey",
            table,
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(f"{table}_user_id_idx", table, ["user_id"])


def downgrade() -> None:
    # Downgrading DISCARDS ownership (user_id -> NULL): the users table is
    # dropped below, so keeping the uuids would make a later re-upgrade see
    # "no legacy rows" yet fail its FK creation. Dev-only escape hatch.
    for table in ("chunks", "documents", "conversations"):
        op.drop_index(f"{table}_user_id_idx", table_name=table)
        op.drop_constraint(f"{table}_user_id_fkey", table, type_="foreignkey")
        op.alter_column(table, "user_id", nullable=True)
        op.execute(f"UPDATE {table} SET user_id = NULL")  # noqa: S608 — table names from a literal tuple
    op.drop_index("email_tokens_user_purpose_idx", table_name="email_tokens")
    op.drop_table("email_tokens")
    op.drop_index("accounts_user_id_idx", table_name="accounts")
    op.drop_table("accounts")
    op.drop_index("users_email_lower_idx", table_name="users")
    op.drop_table("users")
