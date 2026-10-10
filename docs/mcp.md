# Using SILO from Claude and other MCP clients

`silo mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server. It lets an
assistant use your local index as a set of tools: it decides what to search for, reads around
the results, and answers with citations.

## What crosses the boundary

Read this first, because it is the one place SILO's air-gap promise depends on your choice of
client.

| Component | Network use |
|---|---|
| `silo mcp` (the server) | None. It talks to the client over stdin/stdout only. |
| The index store | Opened read-only. No tool can change or delete anything. |
| The client | Whatever the client does. **Claude Desktop and Claude Code send tool results, meaning the passages SILO returns, to Anthropic as part of the conversation.** |

So: with a cloud assistant, retrieval is local and the retrieved passages are not. That is
often exactly what is wanted (the assistant only ever sees the few passages it asks for, not
your document store). It is not air-gapped. For that, use the web interface, `silo ask` with a
local model, or an MCP client driving a local model.

## Setup

Use absolute paths; MCP clients do not start in your project directory.

**Claude Code**

```bash
claude mcp add silo -- /absolute/path/to/silo/.venv/bin/silo mcp
# a specific store, read by this server only:
claude mcp add silo-contracts -- /absolute/path/to/silo/.venv/bin/silo mcp --index /stores/contracts
```

**Claude Desktop** — Settings → Developer → Edit Config, then restart the app:

```json
{
  "mcpServers": {
    "silo": {
      "command": "/absolute/path/to/silo/.venv/bin/silo",
      "args": ["mcp"],
      "env": { "SILO_INDEX": "/absolute/path/to/an/index/store" }
    }
  }
}
```

Omit `env` to use the default store. Any other MCP client that can launch a stdio server is
configured the same way: command `silo`, argument `mcp`.

## Tools

All five are marked read-only.

| Tool | Arguments | Returns |
|---|---|---|
| `search_documents` | `query`, `limit` (1–25, default 8), `mode` (`hybrid`, `semantic`, `keyword`) | Ranked passages with `passage_id`, `document_id`, file, page, section, score, text |
| `get_passage_context` | `passage_id`, `before` (default 2), `after` (default 2) | The passage and its neighbours in reading order |
| `read_document` | `document_id`, `start`, `count` (max 20) | Passages in order, with `next_start` for paging |
| `list_documents` | `contains`, `limit` | Document ids, files, titles, page and passage counts |
| `index_status` | — | Store location and id, counts, embedding model, source folders |

Passages are capped at 4,000 characters each.

## What to ask

- *"Use silo to find what the supplier agreement says about liability caps. Quote the clause
  and give the page."*
- *"Search silo for every mention of PR.AA-05 and summarise what each document requires."*
- *"List the documents in silo, then read the introduction of the zero trust paper and
  explain its scope."*

Assistants do better with several narrow searches than one broad one, and the server's
instructions tell them so. Exact identifiers work best in `keyword` mode.

## Checked

- The test suite starts `silo mcp` as a subprocess and drives it with the official MCP client:
  tool listing, search, context, paged reading, status and error handling.
- Claude Code, run headless with only the SILO tools allowed, answered a question about a
  control identifier in the sample corpus with the correct file and page, using one
  `search_documents` call in keyword mode.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Client shows no tools | Wrong path to `silo`, or the virtual environment was moved. Run the command by hand: it should wait silently for input. |
| "No index store at …" | Nothing indexed yet, or `SILO_INDEX` points at the wrong directory. |
| "Models not found …" | Run `silo models pull` on this machine. |
| First search takes a couple of seconds | Models load on first use, then stay loaded. |
