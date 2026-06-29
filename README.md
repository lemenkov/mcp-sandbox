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
| `python`  | Python 3 + numpy, matplotlib, scipy, pandas, sympy, scikit-learn, obspy |
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
- Output files collected from `/sandbox/output/` (base64)

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

## Configuration

```
HOST=127.0.0.1
PORT=8815
SANDBOX_IMAGE=mcp-sandbox:latest
DEFAULT_TIMEOUT=60
MAX_TIMEOUT=300
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
