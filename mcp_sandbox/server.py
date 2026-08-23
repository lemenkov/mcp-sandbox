# SPDX-FileCopyrightText: 2026 Peter Lemenkov <lemenkov@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""MCP server for isolated scientific script execution."""

import argparse
import asyncio
import base64
import hashlib
import logging
import mimetypes
import os
import secrets
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastmcp import FastMCP

PUBLIC_DIR = Path(
    os.environ.get("SANDBOX_PUBLIC_DIR", "/var/cache/mcp-sandbox/outputs")
)
PUBLIC_BASE_URL = os.environ.get("SANDBOX_PUBLIC_BASE_URL", "").rstrip("/")
PUBLIC_TTL = int(os.environ.get("SANDBOX_PUBLIC_TTL", "3600"))
INLINE_MAX = int(os.environ.get("SANDBOX_INLINE_MAX_BYTES", "4096"))  # tiny text only
SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "mcp-sandbox:latest")
MAX_TIMEOUT = int(os.environ.get("MAX_TIMEOUT", "300"))
DEFAULT_TIMEOUT = int(os.environ.get("DEFAULT_TIMEOUT", "60"))

mcp = FastMCP("Scientific Sandbox")

# All runtimes receive script via stdin
RUNTIMES = {
    "r": ["Rscript", "-"],
    "python": ["python3", "-"],
    "bash": ["bash", "-s"],
    "gmt": ["bash", "-s"],
    "octave": ["octave", "--no-gui"],
    "julia": ["julia", "--startup-file=no", "-"],
    "gnuplot": ["gnuplot"],
    "grass": [
        "bash",
        "-c",
        "cat > /sandbox/script.sh && "
        "grass --tmp-project XY "
        "--exec bash /sandbox/script.sh",
    ],
    "latex": [
        "bash",
        "-c",
        "cat > /sandbox/script.tex && pdflatex "
        "-interaction=nonstopmode "
        "-output-directory=/sandbox/output "
        "/sandbox/script.tex",
    ],
}


def _safe_name(filename: str) -> str:
    """Reduce a caller-supplied filename to a single safe path component.
    Normalizes Windows-style separators (submissions may originate off-Linux)
    and rejects empty or traversal names ('', '.', '..')."""
    name = Path(filename.replace("\\", "/")).name
    if name in ("", ".", ".."):
        raise ValueError(f"unsafe input filename {filename!r}")
    return name


def _decode_input_file(filename: str, data: str) -> bytes:
    """Decode a base64 input-file payload. Tolerates whitespace, a data: URI
    prefix, the URL-safe alphabet, and stripped '=' padding; still rejects
    genuinely non-base64 content with a clear, named error."""
    s = "".join(data.split())  # drop line-wraps / stray whitespace
    if s.startswith("data:") and "," in s:  # strip a data:<mime>;base64, prefix
        s = s.split(",", 1)[1]
    s = s.replace("-", "+").replace("_", "/")  # accept URL-safe alphabet
    s += "=" * (-len(s) % 4)  # restore stripped padding
    try:
        return base64.b64decode(s, validate=True)
    except ValueError as e:
        raise ValueError(
            f"input file {filename!r}: not valid base64 ({e}); "
            f"input_files maps filename -> base64-encoded bytes. If this is "
            f"text, pass it via text_files (filename -> UTF-8 text) instead."
        ) from e


def _publish_outputs(output_path: Path) -> list[dict]:
    """Move sandbox outputs to the web-served staging dir under a per-run
    capability token; return metadata (+ url), never raw bytes. Small text
    files are additionally inlined for one-round-trip convenience."""
    files = [p for p in sorted(output_path.iterdir()) if p.is_file()]
    if not files:
        return []
    token = secrets.token_urlsafe(32)  # ~256-bit capability
    dest = PUBLIC_DIR / token
    dest.mkdir(parents=True, exist_ok=True)
    results = []
    for p in files:
        name = Path(p.name).name  # basename only — no traversal
        size = p.stat().st_size
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        shutil.move(str(p), str(dest / name))
        (dest / name).chmod(0o644)  # nginx must read it
        meta = {
            "name": name,
            "bytes": size,
            "sha256": digest,
            "mime": mime,
            "url": f"{PUBLIC_BASE_URL}/{token}/{quote(name)}"
            if PUBLIC_BASE_URL
            else None,
            "expires_in": PUBLIC_TTL,
        }
        if mime.startswith("text/") and size <= INLINE_MAX:
            meta["text"] = (dest / name).read_text("utf-8", "replace")
        results.append(meta)
    return results


async def _run_container(
    runtime: str,
    script: str,
    input_files: dict[str, str],
    text_files: dict[str, str],
    timeout: int,
) -> dict:
    """Run a script in an isolated podman container via stdin."""
    cmd = RUNTIMES[runtime]

    with (
        tempfile.TemporaryDirectory(prefix="mcp-sandbox-input-") as input_dir,
        tempfile.TemporaryDirectory(prefix="mcp-sandbox-out-") as out_dir,
    ):
        os.chmod(out_dir, 0o777)

        input_path = Path(input_dir)

        try:
            for filename, b64content in (input_files or {}).items():
                safe_name = _safe_name(filename)
                (input_path / safe_name).write_bytes(
                    _decode_input_file(safe_name, b64content)
                )

            for filename, content in (text_files or {}).items():
                safe_name = _safe_name(filename)
                (input_path / safe_name).write_text(content, encoding="utf-8")
        except ValueError as e:
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": "",
                "output_files": [],
            }

        podman_args = [
            "podman",
            "run",
            "--rm",
            "--timeout",
            "300",
            "--network=host",
            "--security-opt",
            "no-new-privileges",
            "--security-opt",
            "label=disable",
            "--memory",
            "2g",
            "--cpus",
            "2",
            "--tmpfs",
            "/tmp:rw,size=512m",
            "-v",
            f"{out_dir}:/sandbox/output:rw",
            "-i",
        ]

        if input_files or text_files:
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
                "stdout": "",
                "stderr": "",
                "output_files": [],
            }

        # Collect output files from host-side tmpdir
        # Publish outputs as capability URLs (metadata only) instead of
        # inlining base64 into the response / model context.
        output_files = _publish_outputs(Path(out_dir))

        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "output_files": output_files,
        }


@mcp.tool(
    tags={"write"},
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    },
)
async def run_script(
    runtime: str,
    script: str,
    input_files: Optional[dict[str, str]] = None,
    text_files: Optional[dict[str, str]] = None,
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
    return await _run_container(
        runtime, script, input_files or {}, text_files or {}, timeout
    )


@mcp.tool(
    tags={"read"},
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
async def list_runtimes() -> dict:
    """List available scientific runtimes in the sandbox."""
    return {
        "runtimes": {name: {"command": cmd[0]} for name, cmd in RUNTIMES.items()},
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
