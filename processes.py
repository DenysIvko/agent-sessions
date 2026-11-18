"""Read process metadata without launching an agent or executing session text."""

from pathlib import Path
import psutil


def matching_processes(source):
    for process in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            name = (process.info["name"] or "").lower().removesuffix(".exe")
            executable = (process.info["exe"] or "").lower().replace("\\", "/")
            command = process.info["cmdline"] or []
            if source == "antigravity":
                matches = name == "agy" or name == "language_server" and "antigravity" in executable
            else:
                matches = name == source or (name == "node" and any(
                    f"/{source}" in arg.lower().replace("\\", "/") and arg.endswith((".js", ".cjs"))
                    for arg in command[1:2]))
            if matches:
                yield process
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def open_files(processes):
    files = set()
    for process in processes:
        try:
            files.update(Path(item.path) for item in process.open_files())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return files
