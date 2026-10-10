# Index stores

An **index store** is one directory. It contains everything SILO derived from your documents
and nothing else:

```
my-store/
├── catalogue.sqlite    documents: path, hash, pages, status, plus the store's own manifest
└── lance/              passages, their vectors and the BM25 keyword index
```

Models are not part of a store. They stay in `$SILO_HOME/models` on each machine.

## Choosing which store to use

In order of precedence:

| How | Scope |
|---|---|
| `--index <path>` on any command | That one command |
| `SILO_INDEX=<path>` | That shell or service |
| `silo store use <path> [--read-only]` | Every command from now on (written to `config.toml`) |
| nothing | `$SILO_HOME/index` |

`silo store use --default` returns to the built-in location. `silo doctor` and
`silo store info` both show which store is active.

```console
$ silo store info
Index store /Users/me/.silo/index
  store id         0833f84841c3
  embedding model  BAAI/bge-small-en-v1.5
  passage size     384 tokens
  documents        6 (6 indexed, 0 empty, 0 failed)
  pages / passages 227 / 544
  size on disk     3.6 MB
  writable here    yes
  source folder    /Users/me/silo/sample-corpus  (present)
```

## Several stores on one machine

Keep unrelated collections apart: one store per client, project or sensitivity level.

```bash
silo index ~/clients/acme  --index ~/stores/acme
silo index ~/clients/bravo --index ~/stores/bravo
silo serve --index ~/stores/acme --port 8321
silo serve --index ~/stores/bravo --port 8322
```

## Taking a store to another machine

Copy the directory. That is the whole export format.

```bash
rsync -a ~/stores/acme/ other-machine:stores/acme/
# on the other machine (models already pulled there):
silo search "termination clause" --index ~/stores/acme
```

- **Models follow the store.** The store records which embedding model built it. SILO uses
  that model when opening the store and tells you if it differs from your configuration. If
  the model is not downloaded on this machine, you get a clear error naming it.
- **Search works without the source files.** The store holds the extracted text, so results,
  headings and page numbers all work. Opening the original file needs the file.
- **If the files are there but at a different path**, re-point the store instead of
  re-indexing:

  ```bash
  silo store relocate /srv/documents/acme ~/Documents/acme
  ```

  Document ids are kept, so nothing is re-parsed and later `silo index` runs stay incremental.

## Sharing one store

Put the store on a shared drive and open it read-only everywhere except the one machine that
maintains it:

```bash
silo store use /Volumes/team/silo-index --read-only    # each reader
silo index /Volumes/team/documents --index /Volumes/team/silo-index   # the maintainer
```

Read-only mode opens the catalogue with SQLite's read-only flag, never creates files, and
refuses indexing, reset and re-scan (the API returns 403).

## Limits to know about

- **A store is not an access boundary.** Anyone who can read the directory can read all the
  extracted text in it. Split stores by audience, and use file permissions on the directory.
- **One writer.** Indexing into the same store from two machines at once is not coordinated.
- **Network drives.** Reading a store over SMB or NFS works. Query speed then depends on the
  share; a local copy is faster. Do not index over a flaky connection.
- **Readers see updates when they reopen.** A running `silo serve` picks up new passages, but
  restart it after a large re-index to be sure of a consistent view.
- **Same major version.** Stores are compatible across SILO 0.x releases that keep the same
  schema; `created with` in `store info` records where a store came from.
