<!--
SPDX-FileCopyrightText: 2026 Peter Lemenkov <lemenkov@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# mcp-sandbox

MCP server for isolated scientific script execution. Run R, Python, GMT,
GRASS GIS, LaTeX, Octave, Julia, and more in disposable containers — fully
stateless, no host filesystem access.

## Tools

| Tool            | Description                                       |
| --------------- | ------------------------------------------------- |
| `run_script`    | Execute a script in an isolated sandbox container |
| `list_runtimes` | List available scientific runtimes                |

## Supported Runtimes

| Runtime   | Tools                                                                   |
| --------- | ----------------------------------------------------------------------- |
| `r`       | R + ggplot2, dplyr, tidyr, jsonlite                                     |
| `python`  | Python 3 + numpy, scipy, pandas, matplotlib, sympy, scikit-learn, geopandas, pyproj, rasterio, obspy |
| `gmt`     | Generic Mapping Tools                                                   |
| `grass`   | GRASS GIS — headless; each run gets a throwaway location                |
| `latex`   | pdflatex (texlive)                                                      |
| `octave`  | GNU Octave                                                              |
| `julia`   | Julia                                                                   |
| `gnuplot` | Gnuplot                                                                 |
| `bash`    | Bash scripts                                                            |

## Design

- Each run spawns a fresh container — **fully stateless, no reuse**
- Container deleted after execution (`--rm`)
- Network access enabled
- Memory limit: 2GB, CPU limit: 2 cores
- Input files injected at `/sandbox/input/` (base64)
- Output files collected from `/sandbox/output/`, returned **by reference**: a
  capability URL plus metadata (name, bytes, SHA-256, MIME, expiry). Small text
  outputs (< 4 KB) are still inlined. See "Output handling" below.

## Install

The sandbox runs containers **rootless, as a dedicated `sandbox` user**. The
image *and* the running service must live in that user's podman store. This
is the single most important thing to get right — see Troubleshooting.

### 1. Create the service user

```
useradd -r -m -d /var/lib/mcp-sandbox -s /bin/bash sandbox
echo "sandbox:100000:65536" >> /etc/subuid
echo "sandbox:100000:65536" >> /etc/subgid
# rootless podman needs a runtime dir (/run/user/<uid>) present at boot:
loginctl enable-linger sandbox
```

### 2. Build the image — *as the `sandbox` user*

Build into the `sandbox` user's rootless store. **Not** your login user's,
**not** root's — the server only ever reads `sandbox`'s store:

```
sudo -u sandbox -H podman build -t mcp-sandbox:latest -f Containerfile .
```

Already built the image elsewhere? Don't rebuild — transfer it across the
store boundary:

```
podman save mcp-sandbox:latest | sudo -u sandbox -H podman load
```

### 3. Install the server

```
python3 -m venv venv
venv/bin/pip install -e .
```

## Running as a service

Run the server as `sandbox` so it reads that user's image store. Minimal
unit (adjust the checkout path and entrypoint to your install):

```
# /etc/systemd/system/mcp-sandbox.service
[Unit]
Description=mcp-sandbox MCP server
After=network.target

[Service]
User=sandbox
ExecStart=/var/lib/mcp-sandbox/mcp-sandbox/venv/bin/mcp-sandbox
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## Adding dependencies

The image is the single source of truth for what a runtime can do. Because every
run is a fresh `--rm` container, a runtime `pip install` inside a sandbox does
**not** persist — it re-downloads and rebuilds on every invocation, and on
current Fedora it hits PEP 668 (`externally-managed-environment`) anyway. So:

- **Missing package?** Add the `python3-*` (or `R-*`, etc.) RPM to the
  `Containerfile` and rebuild the image — don't pip-install at runtime. Prefer
  Fedora RPMs; they keep the image reproducible and versioned in git.
- **No Fedora RPM for it?** Add a build-time `RUN pip install …` layer to the
  `Containerfile`, baked into the image — never a runtime install in the sandbox.

Rebuild after any change (as the `sandbox` user — see Install/Troubleshooting):

    sudo -u sandbox -H podman build -t mcp-sandbox:latest -f Containerfile .

## Output handling

Files written to `/sandbox/output/` are returned **by reference**, not inlined
as base64. After a run, the server stages each output under a fresh unguessable
token and returns a compact metadata record in place of the bytes:

    {
      "name": "figure.png",
      "bytes": 29901,
      "sha256": "…",
      "mime": "image/png",
      "url": "https://host.example/sandbox-out/<token>/figure.png",
      "expires_in": 3600
    }

- **Capability URL.** Each file is staged at `/<token>/<name>`, where `<token>`
  is ~256 bits from a CSPRNG (`secrets.token_urlsafe(32)`). Possessing the URL
  is the authorization to fetch it — there is no separate credential.
- **Small text is still inlined.** Text outputs below 4 KB come back inline; a
  round-trip to read three lines isn't worth it. Everything else is referenced.
- **Bounded lifetime.** Staged files live for a TTL (default 60 min), after
  which the GC timer deletes them and the URL 404s — this bounds the exposure
  window of any leaked URL.
- **Integrity.** The `sha256` lets a consumer verify the bytes, or confirm a
  file's identity without fetching it.

### Serving the staged outputs

nginx serves the staging directory read-only, with listing, logging, and auth
off (the token *is* the authentication):

    location /sandbox-out/ {
        alias /var/cache/mcp-sandbox/outputs/;
        auth_basic off;      # the capability token is the authorization
        autoindex off;       # non-enumerable: no directory listing
        access_log off;      # keep tokens out of logs
        add_header X-Robots-Tag "noindex" always;
    }

On SELinux, the staging dir must carry `httpd_sys_content_t`, applied *before*
it is populated:

    semanage fcontext -a -t httpd_sys_content_t "/var/cache/mcp-sandbox/outputs(/.*)?"
    restorecon -RFv /var/cache/mcp-sandbox/outputs

Expiry is a systemd `.timer` firing every 15 min that deletes token directories
older than the TTL.

## Configuration

```
HOST=127.0.0.1
PORT=8815
SANDBOX_IMAGE=mcp-sandbox:latest
DEFAULT_TIMEOUT=60
MAX_TIMEOUT=300
# Output-by-reference — REPLACE names with the actual ones from the code:
SANDBOX_PUBLIC_URL=https://host.example    # base for capability links
OUTPUT_DIR=/var/cache/mcp-sandbox/outputs  # staging directory
OUTPUT_TTL=3600                            # seconds; keep in sync with GC timer
```

## Troubleshooting

**Rebuilt the image but the server still runs the old one?**
You almost certainly built into the wrong podman store. Containers run
rootless as `sandbox`, which reads *its own* store under
`/var/lib/mcp-sandbox/.local/share/containers`. An image built as your login
user or as root lands in a different store the server never reads — so the
build "succeeds" and changes nothing.

Confirm what the service actually sees, and rebuild/load into that store:

```
sudo -u sandbox -H podman images mcp-sandbox
sudo -u sandbox -H podman build -t mcp-sandbox:latest -f Containerfile .
# or: podman save mcp-sandbox:latest | sudo -u sandbox -H podman load
```

No MCP restart is needed afterwards — each run is a fresh `--rm` container
that resolves `mcp-sandbox:latest` from the `sandbox` store at launch.
Restart the service only when you change the server code or `RUNTIMES`.

## License

Apache-2.0
