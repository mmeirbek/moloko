# PostgreSQL 17 with the pgvector extension (semantic search stays in the one database).
# The extension files come from the pgvector project's official image built for the same
# Debian release and PostgreSQL major version; the server itself is the current postgres
# image (security fixes), so the two are bumped independently.
FROM pgvector/pgvector:0.8.1-pg17-trixie AS pgvector

FROM postgres:17.11-trixie
COPY --from=pgvector /usr/lib/postgresql/17/lib/vector.so /usr/lib/postgresql/17/lib/
COPY --from=pgvector /usr/lib/postgresql/17/lib/bitcode/vector.index.bc /usr/lib/postgresql/17/lib/bitcode/
COPY --from=pgvector /usr/lib/postgresql/17/lib/bitcode/vector /usr/lib/postgresql/17/lib/bitcode/vector
COPY --from=pgvector /usr/share/postgresql/17/extension/ /tmp/pgvector-extension/
RUN cp /tmp/pgvector-extension/vector* /usr/share/postgresql/17/extension/ && rm -rf /tmp/pgvector-extension
