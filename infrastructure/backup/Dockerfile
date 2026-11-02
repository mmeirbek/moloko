# The `backup` service image: PostgreSQL 17 client tools (pg_dump / pg_restore / psql, as
# before) + restic for the encrypted off-site copies (infrastructure/backup/offsite.sh).
#
# restic 0.19.1 (BSD-2-Clause) comes from its official image, pinned by the multi-arch index
# digest; only the static binary is copied, and its SHA-256 must equal the binary of the
# signed GitHub release (restic_0.19.1_linux_<arch>.bz2, listed in SHA256SUMS, unpacked).
# To update: read the release notes, take the new digest
# (`docker buildx imagetools inspect restic/restic:<version>`) and the unpacked release
# binaries' SHA-256, replace all three here and the row in docs/decisions.md.
FROM restic/restic:0.19.1@sha256:136600b6ff6843d61d355f7f71f460a166429f35de6fd11b568fece3c9a4d510 AS restic

FROM postgres:17.11-alpine
COPY --from=restic /usr/bin/restic /usr/local/bin/restic
# ssh: only for an SFTP repository (sftp:user@host:/path).
RUN case "$(uname -m)" in \
      x86_64) sum=20d4142678d0d95ec11a4759def1b73fd9190abc9ca19e4b62d067c0b387e639 ;; \
      aarch64) sum=2fb45ac6f9071b6f20eb883953a188f9e7c7cb6bbe43c67a2e47ada4e85ee7f0 ;; \
      *) echo "no checksum for $(uname -m)" >&2; exit 1 ;; \
    esac \
 && echo "$sum  /usr/local/bin/restic" | sha256sum -c - \
 && apk add --no-cache openssh-client-default \
 && restic version
