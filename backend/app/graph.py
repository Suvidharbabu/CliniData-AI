"""Neo4j AuraDB driver (one per process, reused across warm invocations)."""
from functools import lru_cache

from neo4j import Driver, GraphDatabase

from .config import get_settings


@lru_cache
def driver() -> Driver:
    s = get_settings()
    return GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))


def run(cypher: str, **params) -> list[dict]:
    records, _, _ = driver().execute_query(cypher, params, database_="neo4j")
    return [r.data() for r in records]
