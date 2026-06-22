<!--
SPDX-FileCopyrightText: 2026 Peter Lemenkov <lemenkov@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# mcp-sandbox

MCP server for isolated scientific script execution. Run R, Python, GMT,
LaTeX, Octave, Julia, and more in disposable containers — fully stateless,
no host filesystem access.

## Tools

| Tool | Description |
|------|-------------|
| `run_script` | Execute a script in an isolated sandbox container |
| `list_runtimes` | List available scientific runtimes |

## Supported Runtimes

| Runtime | Tools |
|---------|-------|
| `r` | R + ggplot2, dplyr, tidyr, jsonlite |
| `python` | Python 3 + numpy, matplotlib, scipy, pandas, sympy, scikit-learn |
| `gmt` | Generic Mapping Tools |
| `latex` | pdflatex (texlive) |
| `octave` | GNU Octave |
| `julia` | Julia |
| `gnuplot` | Gnuplot |
| `bash` | Bash scripts |

## Design

- Each run spawns a fresh container — **fully stateless, no reuse**
- Container deleted after execution (`--rm`)
- Network access enabled
- Memory limit: 2GB, CPU limit: 2 cores
- Input files injected at `/sandbox/input/` (base64)
- Output files collected from `/sandbox/output/` (base64)

## Build the sandbox image

```bash
podman build -t mcp-sandbox:latest -f Containerfile .
```

## Install

```bash
useradd -r -m -d /var/lib/mcp-sandbox sandbox
echo "sandbox:100000:65536" >> /etc/subuid
echo "sandbox:100000:65536" >> /etc/subgid

python3 -m venv venv
venv/bin/pip install -e .
```

## Configuration

```bash
HOST=127.0.0.1
PORT=8815
SANDBOX_IMAGE=mcp-sandbox:latest
DEFAULT_TIMEOUT=60
MAX_TIMEOUT=300
```

## License

Apache-2.0
