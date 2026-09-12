"""Short-lived human review context and a deliberately small resolution grammar."""

import re

from rich.console import Console

from goflight_memory.core.models import Conflict
from goflight_memory.core.resolve import ResolveError, conflict_revision, list_conflicts, resolve_conflict
from goflight_memory.infra.paths import ProjectPaths
from goflight_memory.wiki.naming import normalized


def is_conflict_list(message: str) -> bool:
    return bool(re.fullmatch(r"(?:show|list)(?: me)?(?: the)?(?: unresolved)? conflicts[.!?]?", message, re.I))


def is_resolution_request(message: str) -> bool:
    return bool(message.startswith("/resolve") or re.match(r"for conflict-|number \d+ (?:should be|is)|.+ is correct for .+ conflict", message, re.I))


def show_conflicts(console: Console, paths: ProjectPaths) -> list[tuple[str, Conflict]]:
    listing = list_conflicts(paths=paths)
    console.print(f"Memory › I found {len(listing)} unresolved conflict{'s' if len(listing) != 1 else ''}.")
    for number, (name, conflict) in enumerate(listing, 1):
        console.print(f"\n{number}. {conflict.conflict_id} — {conflict.entity_name}.{conflict.field}\nPage: {name}", markup=False)
        for fact in conflict.evidence:
            console.print(f"  • {fact.value} — {fact.source_id} — {fact.contributor}", markup=False)
    if listing:
        console.print("Use 'Number 1 should be <value>. <reason>' or /resolve <conflict-id>. Nothing changes until you confirm yes.")
    return listing


def review_resolution(message: str, listing: list[tuple[str, Conflict]], reviewer: str,
                      paths: ProjectPaths, console: Console) -> None:
    selector = value = reason = ""
    if message.startswith("/resolve "):
        selector = message.removeprefix("/resolve ").strip()
    else:
        match = re.fullmatch(r"For (conflict-[0-9a-f]{16}), (.+?) is correct\.\s*(.+)", message, re.I)
        numbered = re.fullmatch(r"Number (\d+) should be (.+?)\.\s*(.+)", message, re.I)
        named = re.fullmatch(r"(.+?) is correct for (?:the )?(.+?) conflict\.\s*(.+)", message, re.I)
        if match:
            selector, value, reason = match.groups()
        elif numbered:
            number, value, reason = numbered.groups()
            if not 1 <= int(number) <= len(listing):
                raise ResolveError("That number is not in the last conflict listing; show conflicts again")
            selector = listing[int(number) - 1][1].conflict_id
        elif named:
            value, selector, reason = named.groups()
        else:
            raise ResolveError("Use /resolve <conflict-id> to enter a value and reason, or show conflicts first")

    current = list_conflicts(paths=paths)
    compact = lambda text: re.sub(r"\W|_", "", normalized(text))
    matches = [(name, c) for name, c in current if c.conflict_id == selector.lower() or (
        compact(c.entity_name) in compact(selector) and compact(c.field) in compact(selector)
    )]
    if len(matches) != 1:
        raise ResolveError("No unique unresolved conflict matches; show conflicts again")
    name, conflict = matches[0]
    if not value:
        value = console.input("Current value or qualified statement (blank cancels) › ").strip()
        if not value:
            console.print("Resolution cancelled; conflict remains unresolved.")
            return
        reason = console.input("Reason › ").strip()
    if not reason.strip():
        raise ResolveError("A reason is required; no changes made")
    # Expand an unambiguous human shorthand only; the exact expansion is previewed.
    values = set(f.value for f in conflict.evidence)
    candidates = [existing for existing in values if normalized(value) in normalized(existing)]
    if value not in values and len(candidates) == 1:
        value = candidates[0]
    console.print(f"\nYou are resolving {conflict.conflict_id}:\n{conflict.entity_name}.{conflict.field}\n"
                  "Current conflicting values:", markup=False)
    for fact in conflict.evidence:
        console.print(f"• {fact.value} — {fact.source_id} — {fact.contributor}", markup=False)
    console.print(f"Proposed resolution: {value}\nReviewer: {reviewer}\nReason: {reason}", markup=False)
    if console.input("Confirm? yes/no › ").strip().lower() != "yes":
        console.print("Resolution cancelled; no changes made.")
        return
    result = resolve_conflict(conflict.conflict_id, value, reviewer, reason, paths=paths,
                              expected_revision=conflict_revision(conflict))
    console.print(f"Memory › Resolved {result.conflict.conflict_id} by {reviewer}.\nGit commit: {result.git_commit[:7]}", markup=False)
