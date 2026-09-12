"""Git commands and transaction-scoped staging. No shell interpolation."""

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


class GitRepository:
    def __init__(self, root: Path):
        self.root = root

    def run(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.root), *args], capture_output=True, text=True,
        )
        if result.returncode:
            raise GitError(result.stderr.strip() or f"Git {args[0]} failed")
        return result.stdout.strip()

    def head(self) -> str:
        return self.run("rev-parse", "HEAD")

    def preflight(self, pending_source: Path | None = None) -> None:
        if Path(self.run("rev-parse", "--show-toplevel")).resolve() != self.root:
            raise GitError("Memory must live at the selected Git repository root")
        self.head()  # Require a foundation commit, so rollback can restore the index.
        self.run("var", "GIT_AUTHOR_IDENT")
        self.run("var", "GIT_COMMITTER_IDENT")
        if self.run("diff", "--cached", "--name-only"):
            raise GitError("Commit or unstage existing staged changes before ingest")
        if self.run("diff", "--name-only", "HEAD", "--", "memory"):
            raise GitError("Commit or restore existing memory edits before ingest")
        untracked = self.run("ls-files", "--others", "--exclude-standard", "-z", "--", "memory")
        allowed = str(pending_source.relative_to(self.root)) if pending_source else None
        if any(name != allowed for name in untracked.split("\0") if name):
            raise GitError("Uncommitted memory exists; retry its original note or review it first")

    def tracked(self, path: Path) -> bool:
        return bool(self.run("ls-files", "--", str(path.relative_to(self.root))))

    def source_commit(self, path: Path) -> str:
        return self.run("log", "-1", "--format=%H", "--", str(path.relative_to(self.root)))

    def commit(self, paths: list[Path], message: str) -> str:
        names = [str(path.relative_to(self.root)) for path in paths]
        if not names or any(not name.startswith("memory/") for name in names):
            raise GitError("Runtime commits must contain only explicit memory paths")
        self.run("add", "--", *names)
        # --only also excludes unrelated files staged by a non-cooperating user mid-ingest.
        self.run("commit", "--only", "-m", message, "--", *names)
        return self.head()

    def unstage(self, paths: list[Path]) -> None:
        indexed = [str(p.relative_to(self.root)) for p in paths if self.tracked(p)]
        if indexed:
            self.run("restore", "--staged", "--", *indexed)
