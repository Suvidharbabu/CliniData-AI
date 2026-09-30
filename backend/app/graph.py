"""Neo4j AuraDB driver (one per process, reused across warm invocations)."""
from functools import lru_cache

import certifi
from neo4j import Driver, GraphDatabase, TrustCustomCAs

from .config import get_settings


@lru_cache
def driver() -> Driver:
    s = get_settings()
    uri, kwargs = s.neo4j_uri, {}
    # Verify TLS against certifi's CA bundle rather than the OS store, which can be
    # incomplete or contain intercepting roots (seen on some Windows machines).
    if "+s://" in uri:
        uri = uri.replace("+s://", "://", 1)
        kwargs = {"encrypted": True, "trusted_certificates": TrustCustomCAs(certifi.where())}
    return GraphDatabase.driver(uri, auth=(s.neo4j_user, s.neo4j_password), **kwargs)


def run(cypher: str, **params) -> list[dict]:
    records, _, _ = driver().execute_query(cypher, params, database_="neo4j")
    return [r.data() for r in records]
