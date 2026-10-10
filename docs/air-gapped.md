# Running air-gapped

## The guarantee and how it is enforced

| Mechanism | Where |
|---|---|
| `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` set before any model library is imported | `src/silo/_offline.py` |
| Telemetry disabled (`HF_HUB_DISABLE_TELEMETRY`, `DO_NOT_TRACK`) in every mode | same |
| Models loaded with `local_files_only=True` from `$SILO_HOME/models` | `embed.py`, `parse.py` |
| Docling `enable_remote_services=False` | `parse.py` |
| Web page ships its own font, script and styles; `Content-Security-Policy: default-src 'self'` | `server.py` |
| Downloads isolated in a child process started only by `silo models pull` | `models.py` |

With no LLM configured, no SILO component opens an outbound connection.

## Installing on a machine with no internet

On a connected machine with the **same OS and CPU architecture**:

```bash
git clone https://github.com/parrytechnologies/silo.git && cd silo
uv sync
uv run silo models pull
# bundle the code + virtual environment, and the models
tar czf silo-app.tgz -C .. silo
tar czf silo-models.tgz -C ~/.silo models
```

Transfer both archives by your approved route, then on the isolated machine:

```bash
tar xzf silo-app.tgz && mkdir -p ~/.silo && tar xzf silo-models.tgz -C ~/.silo
cd silo && .venv/bin/silo doctor
```

The virtual environment contains absolute paths, so unpack it at the same path it was built at,
or build wheels instead (`uv export` + `pip download`) and install from that local directory.
The container image in `Dockerfile` is the more repeatable route: build once, `docker save`,
carry the tarball across, `docker load`.

## Verifying

```bash
silo doctor
```

checks that the models are on disk, the libraries are in offline mode, and reports where the
LLM endpoint (if any) lives. For stronger evidence, run a full cycle with the network removed:

```bash
./scripts/verify-airgap-macos.sh <folder>       # macOS sandbox, outbound denied
unshare -rn silo index <folder>              # Linux, empty network namespace
docker run --rm --network none ...              # container with no network
```

The macOS script first proves the sandbox blocks a real HTTPS request, then indexes and
searches inside it.

## What "air-gapped" does not cover

- `silo mcp` hands passages to an MCP client. If that client is a cloud assistant such as
  Claude, those passages leave the machine. The server itself opens no connections.
- If you configure an external LLM endpoint, retrieved passages are sent to it. `doctor` and
  the interface label this as `external`.
- The index contains the text of your documents. Protect `$SILO_HOME/index` accordingly.
- `silo serve --host 0.0.0.0` exposes search to the network with no authentication.
