# SPDX-FileCopyrightText: 2026 Peter Lemenkov <lemenkov@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""MCP server for isolated scientific script execution."""

import argparse
import asyncio
import base64
import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "mcp-sandbox:latest")
MAX_TIMEOUT = int(os.environ.get("MAX_TIMEOUT", "300"))
DEFAULT_TIMEOUT = int(os.environ.get("DEFAULT_TIMEOUT", "60"))

mcp = FastMCP("Scientific Sandbox")

# All runtimes receive script via stdin
RUNTIMES = {
    "r":       ["Rscript", "-"],
    "python":  ["python3", "-"],
    "bash":    ["bash", "-s"],
    "gmt":     ["bash", "-s"],
    "octave":  ["octave", "--no-gui"],
    "julia":   ["julia", "--startup-file=no", "-"],
    "gnuplot": ["gnuplot"],
    "latex":   ["bash", "-c",
                "cat > /sandbox/script.tex && pdflatex "
                "-interaction=nonstopmode "
                "-output-directory=/sandbox/output "
                "/sandbox/script.tex"],
}


async def _run_container(
    runtime: str,
    script: str,
    input_files: dict[str, str],
    timeout: int,
) -> dict:
    """Run a script in an isolated podman container via stdin."""
    cmd = RUNTIMES[runtime]

    with tempfile.TemporaryDirectory(prefix="mcp-sandbox-input-") as input_dir, \
         tempfile.TemporaryDirectory(prefix="mcp-sandbox-out-") as out_dir:

        os.chmod(out_dir, 0o777)

        input_path = Path(input_dir)

        for filename, b64content in (input_files or {}).items():
            safe_name = Path(filename).name
            (input_path / safe_name).write_bytes(base64.b64decode(b64content))

        podman_args = [
            "podman", "run",
            "--rm",
            "--network=host",
            "--security-opt", "no-new-privileges",
            "--security-opt", "label=disable",
            "--memory", "2g",
            "--cpus", "2",
            "--tmpfs", "/tmp:rw,size=512m",
            "-v", f"{out_dir}:/sandbox/output:rw",
            "-i",
        ]

        if input_files:
            podman_args += ["-v", f"{input_dir}:/sandbox/input:ro"]

        podman_args += [SANDBOX_IMAGE, *cmd]

        try:
            proc = await asyncio.create_subprocess_exec(
                *podman_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=script.encode()),
                timeout=timeout + 5,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return {
                "success": False,
                "error": f"Execution timed out after {timeout}s",
                "stdout": "", "stderr": "", "output_files": {},
            }

        # Collect output files from host-side tmpdir
        output_files = {}
        for f in Path(out_dir).iterdir():
            if f.is_file():
                output_files[f.name] = base64.b64encode(
                    f.read_bytes()
                ).decode()

        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "output_files": output_files,
        }


@mcp.tool(
    tags={"write"},
    annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
)
async def run_script(
    runtime: str,
    script: str,
    input_files: Optional[dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Execute a script in an isolated sandbox container.

    Script is passed via stdin. Container is deleted after execution — fully
    stateless, no reuse. Output files written to /sandbox/output/ are returned
    as base64. Input files are available at /sandbox/input/.

    Args:
        runtime: Runtime to use (r, python, bash, gmt, octave, julia, gnuplot, latex)
        script: Script content to execute
        input_files: Optional dict of filename→base64 encoded content
        timeout: Max execution time in seconds (default 60, max 300)
    """
    if runtime not in RUNTIMES:
        return {
            "success": False,
            "error": f"Unknown runtime '{runtime}'. Available: {', '.join(RUNTIMES)}",
        }

    timeout = min(timeout, MAX_TIMEOUT)
    return await _run_container(runtime, script, input_files or {}, timeout)


@mcp.tool(
    tags={"read"},
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
async def list_runtimes() -> dict:
    """List available scientific runtimes in the sandbox."""
    return {
        "runtimes": {
            name: {"command": cmd[0]}
            for name, cmd in RUNTIMES.items()
        },
        "image": SANDBOX_IMAGE,
        "max_timeout": MAX_TIMEOUT,
        "default_timeout": DEFAULT_TIMEOUT,
        "notes": [
            "All scripts passed via stdin",
            "Output files written to /sandbox/output/ returned as base64",
            "Input files available at /sandbox/input/ (passed as base64)",
            "Containers deleted after each run — fully stateless (--rm)",
            "Network access enabled",
            "Memory limit: 2GB, CPU limit: 2 cores",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MCP server for isolated scientific script execution"
    )
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8815")))
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=os.environ.get("MCP_TRANSPORT", "streamable-http"),
    )
    args = parser.parse_args()

    try:
        from systemd.journal import JournalHandler
        handler: logging.Handler = JournalHandler(SYSLOG_IDENTIFIER="mcp-sandbox")
    except ImportError:
        handler = logging.StreamHandler(sys.stderr)

    logging.basicConfig(handlers=[handler], level=logging.INFO)

    if args.transport == "streamable-http":
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
        )
    else:
        mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
