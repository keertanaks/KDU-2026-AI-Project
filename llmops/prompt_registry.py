"""Prompt versioning registry — audit and eval only.

Existing agents are NOT modified to use this registry.
PromptRegistry is for inspection, hashing, and comparison of versioned prompts.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import logging

_log = logging.getLogger(__name__)

PROMPTS_ROOT = Path("prompts")


class PromptRegistry:
    """Load, list, compare, and hash versioned agent prompts."""

    def load(
        self, agent_name: str, version: str = "latest"
    ) -> tuple[str, dict[str, str]]:
        """Load prompt text and metadata for an agent/version.

        Returns (prompt_text, metadata_dict).
        If version == "latest", loads the highest available version.
        Parses YAML-style frontmatter manually (no external dep).
        """
        if version == "latest":
            versions = self.list_versions(agent_name)
            if not versions:
                raise FileNotFoundError(
                    f"No prompt versions found for agent '{agent_name}'"
                )
            version = versions[-1]

        prompt_path = PROMPTS_ROOT / agent_name / f"v{version}.md"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt not found: {prompt_path}")

        raw = prompt_path.read_text(encoding="utf-8")
        metadata, prompt_text = self._parse_frontmatter(raw)
        return prompt_text, metadata

    def list_versions(self, agent_name: str) -> list[str]:
        """Return sorted list of available version strings (e.g. ['1.0', '2.0'])."""
        agent_dir = PROMPTS_ROOT / agent_name
        if not agent_dir.exists():
            return []
        versions: list[str] = []
        for f in sorted(agent_dir.glob("v*.md")):
            ver = f.stem[1:]  # strip leading 'v'
            versions.append(ver)
        return versions

    def compare(self, agent_name: str, v1: str, v2: str) -> dict[str, Any]:
        """Compare two prompt versions. Returns line/char delta and SHA256 hashes."""
        text1, _ = self.load(agent_name, v1)
        text2, _ = self.load(agent_name, v2)
        lines1 = text1.splitlines()
        lines2 = text2.splitlines()
        set1, set2 = set(lines1), set(lines2)
        added = len([l for l in lines2 if l not in set1])
        removed = len([l for l in lines1 if l not in set2])
        return {
            "added_lines": added,
            "removed_lines": removed,
            "char_delta": len(text2) - len(text1),
            "v1_hash": self._sha256(text1),
            "v2_hash": self._sha256(text2),
        }

    def get_hash(self, agent_name: str, version: str = "latest") -> str:
        """Return SHA256 hex digest of the prompt text."""
        text, _ = self.load(agent_name, version)
        return self._sha256(text)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _sha256(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
        """Split YAML frontmatter from body; parse simple key: value lines.

        Expects the file to start with '---', contain key: value lines,
        and close with another '---'. Everything after is the prompt body.
        Returns (metadata_dict, prompt_text).
        """
        lines = raw.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}, raw

        metadata: dict[str, str] = {}
        end_idx = 1
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                end_idx = i
                break
            if ":" in line:
                key, _, val = line.partition(":")
                cleaned_val = val.strip().strip('"').strip("'")
                metadata[key.strip()] = cleaned_val

        prompt_text = "\n".join(lines[end_idx + 1 :]).strip()
        return metadata, prompt_text
