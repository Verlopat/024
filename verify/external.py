"""Run installed external checkers if available; never invent a verdict."""
import shutil
import subprocess
from pathlib import Path


def check_external(root: Path, folder: Path, timeout: int = 30) -> list[dict]:
    results = []
    for name, command in [("genmc", ["genmc", "verify/harness.cpp"]),
                          ("nidhugg", ["nidhuggc", "--tso", "verify/harness.cpp"])]:
        tool = command[0]
        item = {"checker": name, "command": command,
                "status": "not_run_tool_unavailable", "verified_model": None}
        if shutil.which(tool):
            try:
                result = subprocess.run(command, cwd=root, text=True,
                                        capture_output=True, timeout=timeout)
                (folder / f"{name}.stdout.txt").write_text(result.stdout)
                (folder / f"{name}.stderr.txt").write_text(result.stderr)
                item.update({"status": "completed" if result.returncode == 0 else "tool_error_or_counterexample",
                             "returncode": result.returncode,
                             "verified_model": "must_confirm_from_tool_version_and_output"})
            except subprocess.TimeoutExpired:
                item["status"] = "timeout"
            except OSError as exc:
                item["status"] = "tool_error"
                item["error"] = str(exc)
        results.append(item)
    return results
