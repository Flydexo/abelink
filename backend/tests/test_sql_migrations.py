"""Validate startup SQL with PostgreSQL's parser without a live database."""

import pytest
from pglast import ast, parse_sql
from pglast.visitors import Visitor
from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql

from app.db.models import ProfileORM
from app.db.session import MIGRATIONS_DIR


@pytest.mark.parametrize("migration", sorted(MIGRATIONS_DIR.glob("*.sql")), ids=lambda path: path.name)
def test_startup_migration_has_valid_postgresql_syntax(migration):
    assert parse_sql(migration.read_text(encoding="utf-8"))


def test_search_vector_reads_profile_role_not_database_session_role():
    statements = parse_sql((MIGRATIONS_DIR / "001_init.sql").read_text(encoding="utf-8"))
    profiles = next(
        statement.stmt for statement in statements
        if isinstance(statement.stmt, ast.CreateStmt) and statement.stmt.relation.relname == "profiles"
    )
    search_column = next(column for column in profiles.tableElts if column.colname == "search_tsv")
    generated_expression = next(constraint.raw_expr for constraint in search_column.constraints if constraint.raw_expr)

    class ExpressionReferences(Visitor):
        def __init__(self):
            super().__init__()
            self.columns = []
            self.session_values = []

        def visit_ColumnRef(self, ancestors, node):
            self.columns.append(tuple(field.sval for field in node.fields))

        def visit_SQLValueFunction(self, ancestors, node):
            self.session_values.append(node)

    references = ExpressionReferences()
    references(generated_expression)
    assert ("current_role",) in references.columns
    assert not references.session_values


@pytest.mark.parametrize("statement", [
    select(ProfileORM.current_role),
    update(ProfileORM).values(current_role="Engineer"),
])
def test_orm_quotes_current_role_in_postgresql(statement):
    compiled = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert '"current_role"' in compiled
    assert parse_sql(compiled)
