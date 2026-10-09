# From one machine to an organisation

## What the open engine does on its own

A single person, or a small trusted team on one host, can run Sextant as it is.

**Keep the index fresh with cron.** Indexing is incremental and exits non-zero if any file
failed, so it is safe to schedule:

```cron
# every night at 01:30: pick up new, changed and deleted files
30 1 * * *  SEXTANT_HOME=/srv/sextant /opt/sextant/.venv/bin/sextant index /srv/documents --quiet >> /var/log/sextant-index.log 2>&1
```

**Keep the interface running with systemd.**

```ini
# /etc/systemd/system/sextant.service
[Unit]
Description=Sextant document search
After=network.target

[Service]
User=sextant
Environment=SEXTANT_HOME=/srv/sextant
ExecStart=/opt/sextant/.venv/bin/sextant serve
Restart=on-failure
# belt and braces: the service may only talk to itself
IPAddressDeny=any
IPAddressAllow=localhost

[Install]
WantedBy=multi-user.target
```

Stop the service while a scheduled index run writes, or accept that results update when the
run finishes: the engine does not coordinate concurrent writers.

## Where the engine stops

The engine binds to localhost and trusts whoever can reach it. Before it is offered to a
department or a company, these need answers, and they are specific to each organisation:

| Question | Why it is not in the engine |
|---|---|
| Who may see which documents? | Access rules live in your directory and file permissions. Search must filter by them, or it becomes the easiest way to read files you cannot open. |
| How do users sign in? | SSO (Entra ID, Okta, Keycloak…) and session handling sit in front of the API. |
| Where do documents live? | File shares, SharePoint, a DMS, mailboxes — each needs a connector and a change feed, not a nightly walk. |
| How big, how fast? | Tens of thousands of pages index overnight on one CPU host. Millions need parallel workers and a queue. |
| What proves it works? | An evaluation set drawn from your own documents and real questions, measured before and after every change. |
| Which LLM, hosted where? | Model choice, hardware sizing, and whether passages may leave the network. |
| Who operates it? | TLS, backups, monitoring, audit logs, upgrades. |

## The service

Parry Technologies deploys Sextant on an organisation's own infrastructure and builds the layer
above: authentication and permission-aware search, connectors and scheduled indexing,
multi-user serving, a local or hosted LLM, and an evaluation on your documents so quality is
measured rather than assumed. The engine stays open source, so nothing about the core is a
black box and there is no licence lock-in.

Contact: parryh@parrytech.co · https://parrytech.co/contact
