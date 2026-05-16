"""Layer 5 / Phase 8: Output Generator — assemble FinalOutput, write output.json, render PNGs.

Fills family, environment, and rationale fields left empty by the NKBA validator,
then serializes to disk and delegates rendering to render.py.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import subprocess
import time
import uuid
from typing import Any

import anthropic

from agents.rationale_writer import RationaleWriter
from dtos.contracts import FinalOutput, VariantSummaryDTO, ZonePlannerOutput
from utils.logger import get_logger

logger = get_logger(__name__)


class OutputGenerator:
    """Assemble, enrich, serialize, and render kitchen layout variants."""

    def __init__(
        self,
        client: anthropic.Anthropic,
        out_dir: str = "renders",
    ) -> None:
        """Initialise with Anthropic client and output directory."""
        self._writer = RationaleWriter(client)
        self._out_dir = out_dir

    async def generate(
        self,
        validated_variants: list[VariantSummaryDTO],
        zone_variants: list[ZonePlannerOutput],
        input_json: dict[str, Any],
        start_time: float,
        output_path: str = "output.json",
    ) -> FinalOutput:
        """Build FinalOutput, write output.json, and trigger render.py.

        Steps:
          1. Sort variants by score descending.
          2. Build family_map from zone_variants.
          3. Write rationale for all variants in parallel.
          4. Build structural layout items from input_json["environment"].
          5. Fill family / environment / rationale / layout on each variant.
          6. Assemble FinalOutput.
          7. Write output.json.
          8. Run render.py subprocess (non-fatal on failure).
          9. Return FinalOutput.
        """
        # 1. Sort by score descending
        sorted_variants = sorted(validated_variants, key=lambda v: v.score, reverse=True)

        # 2. Family map from zone planner outputs
        family_map: dict[str, str] = {zv.variant_id: zv.family for zv in zone_variants}

        # 3. Parallel rationale writing
        rationales: list[list[dict[str, Any]]] = list(
            await asyncio.gather(*[self._writer.write(v) for v in sorted_variants])
        )

        # 4. Structural items (walls + openings)
        env = input_json.get("environment", {})
        structural_items = self._build_structural_items(env)

        # 5. Enrich each variant
        complete_variants: list[VariantSummaryDTO] = []
        for i, variant in enumerate(sorted_variants):
            enriched = dataclasses.replace(
                variant,
                family=family_map.get(variant.id, variant.family),
                environment=env,
                rationale=rationales[i],
                layout={**structural_items, **variant.layout},
            )
            complete_variants.append(enriched)

        # 6. Assemble FinalOutput
        output = FinalOutput(
            request_id=str(uuid.uuid4()),
            duration_ms=(time.time() - start_time) * 1000.0,
            layouts=complete_variants,
        )

        # 7. Write output.json
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(self._to_json_dict(output), fh, indent=2)
        logger.info("Wrote output to '%s'", output_path)

        # 8. Render PNGs
        logger.info(
            "Rendering PNGs for %d variants -> %s",
            len(output.layouts),
            self._out_dir,
        )
        result = subprocess.run(
            ["python", "render.py", output_path, "--out-dir", self._out_dir],
            check=False,
        )
        if result.returncode != 0:
            logger.warning("render.py exited with code %d", result.returncode)
        else:
            logger.info("Render complete")

        return output

    # ------------------------------------------------------------------ #
    # Structural items builder                                             #
    # ------------------------------------------------------------------ #

    def _build_structural_items(self, env: dict[str, Any]) -> dict[str, Any]:
        """Convert environment walls and openings to layout-format dicts."""
        items: dict[str, Any] = {}

        for wall in env.get("wall", []):
            pts = wall.get("points", [])
            if not pts:
                continue
            xs = [p["x"] for p in pts if "x" in p]
            ys = [p["y"] for p in pts if "y" in p]
            if not xs or not ys:
                continue
            height = float(wall.get("dimensions", {}).get("height", 2700))
            cx = (min(xs) + max(xs)) / 2.0
            cy = (min(ys) + max(ys)) / 2.0
            cz = height / 2.0
            width = float(
                wall.get("dimensions", {}).get("length_mm")
                or max((max(xs) - min(xs)), (max(ys) - min(ys)))
            )
            depth = float(wall.get("thickness_mm", 100))
            items[wall["name"]] = {
                "is_wall": True,
                "position_mm": {"x": cx, "y": cy, "z": cz},
                "dimensions_mm": {"width": width, "depth": depth, "height": height},
                "rotation_z_deg": 0.0,
            }

        for opening in env.get("openings", []):
            wall_anchor = opening.get("wall", "")
            wall_dict = next(
                (
                    w
                    for w in env.get("wall", [])
                    if w.get("anchor") == wall_anchor or w.get("name", "").startswith(wall_anchor)
                ),
                None,
            )
            wall_y = 0.0
            if wall_dict:
                pts = wall_dict.get("points", [])
                if pts:
                    wall_y = float(pts[0].get("y", 0.0))

            offset = float(opening.get("offset_mm", 0))
            width = float(opening.get("width_mm", 900))
            height = float(opening.get("height_mm", 2100))
            kind = opening.get("kind", "door")
            items[opening["id"]] = {
                f"is_{kind}": True,
                "anchor_wall": wall_anchor,
                "position_mm": {"x": offset + width / 2.0, "y": wall_y, "z": height / 2.0},
                "dimensions_mm": {"width": width, "depth": 100.0, "height": height},
                "rotation_z_deg": 0.0,
            }

        return items

    # ------------------------------------------------------------------ #
    # Serialization                                                        #
    # ------------------------------------------------------------------ #

    def _to_json_dict(self, output: FinalOutput) -> dict[str, Any]:
        """Serialize FinalOutput to a plain dict for json.dump."""
        return {
            "request_id": output.request_id,
            "duration_ms": output.duration_ms,
            "layouts": [
                {
                    "id": v.id,
                    "family": v.family,
                    "score": v.score,
                    "placement_count": v.placement_count,
                    "nkba_compliance_pct": v.nkba_compliance_pct,
                    "spillover_count": v.spillover_count,
                    "warnings": v.warnings,
                    "violations": v.violations,
                    "environment": v.environment,
                    "layout": v.layout,
                    "rationale": v.rationale,
                }
                for v in output.layouts
            ],
        }
