"""Auto-generated rationale lookup table for all 31 NKBA rules.

Maps rule IDs to plain-English explanations. Used by nkba_validator.py
to populate the rationale field without LLM calls.
"""

from __future__ import annotations

# 31-rule explanation table: rule_id → human-readable explanation
RULE_EXPLANATIONS: dict[str, str] = {
    # ── 11 Project Rules (weighted, critical for kitchen function) ──
    "NKBA-CL-01": "Refrigerator clearance in front is less than 1067mm (no easy door swing in tight aisle).",
    "NKBA-CL-02": "Door opening creates conflict with appliances or cabinets (900×900mm clear zone required).",
    "WORKFLOW-01": "Stove landing area (prep counter next to stove) is too small or missing.",
    "WORKFLOW-02": "Sink landing area (counter beside/near sink) is insufficient for food prep.",
    "WORKFLOW-03": "Work triangle perimeter is outside safe range (3962–6600mm); layout too tight or too sprawling.",
    "LAYOUT-01": "Sink is not positioned with a window view when one is available.",
    "LAYOUT-02": "Dishwasher and sink are on different walls or more than 600mm apart (should be adjacent).",
    "LAYOUT-03": "Cabinet run has gaps larger than 50mm between units (violates continuous run principle).",
    "LAYOUT-04": "One or more appliances lack base cabinet support underneath (structural integrity issue).",
    "LAYOUT-05": "Tall cabinet (e.g., pantry) is placed mid-wall without attachment to corner or wall end.",
    "LAYOUT-06": "Cabinet overflow: item forced to corner due to space constraints (spillover penalty applies).",
    # ── 20 Official NKBA Rules (unweighted, best-practice compliance) ──
    "NKBA-01": "Kitchen clearance and traffic flow conflict detected (minimum aisle width violated).",
    "NKBA-02": "Appliance arrangement violates sequence: refrigerator → sink → cooktop should follow work pattern.",
    "NKBA-03": "Work aisle (area used during food prep) is narrower than 1067mm (cramped workflow).",
    "NKBA-04": "Island or peninsula blocks safe traffic pattern through kitchen (accessibility issue).",
    "NKBA-05": "Layout does not accommodate safe access to all appliances and cabinets.",
    "NKBA-06": "Counter work surface is fragmented (less than 4013mm total continuous counter available).",
    "NKBA-06b": "Fridge or range lacks adequate counter support nearby (no proper prep or landing area).",
    "NKBA-07": "Minimum landing area requirements not met near major appliances.",
    "NKBA-08": "Layout does not provide adequate ventilation path from cooktop to hood.",
    "NKBA-10": "Single-wall kitchen without sufficient counter or cabinet depth.",
    "NKBA-11": "Cabinet heights or depths are not standard NKBA-compliant dimensions.",
    "NKBA-12": "Storage accessibility is poor (reach zones too high, cabinets too deep).",
    "NKBA-13": "Dishwasher placement violates standing-room and loading accessibility.",
    "NKBA-LA-01": "Universal design principles not met (counter heights, reach distances).",
    "NKBA-LA-02": "Kitchen does not accommodate aging-in-place requirements (wide aisles, low reach).",
    "NKBA-LA-03": "Layout does not provide clear sight lines from main sink to entry and dining areas.",
    "NKBA-LA-05": "Accessible storage not evenly distributed (relies on high/low cabinets without main-level reach).",
    "NKBA-18": "Refrigerator clearance or door swing conflicts with other appliances or walls.",
    "NKBA-19": "Cooktop or range hood clearance to walls or cabinets below minimum (600mm clearance).",
    "NKBA-25": "Flooring, materials, or finishes do not support easy cleaning and maintenance.",
}


def generate_rationale(violations: list[dict[str, str]]) -> list[dict[str, str]]:
    """Convert violation records to rationale by looking up rule explanations.

    Args:
        violations: List of dicts with 'rule_id' and 'text' keys from nkba_validator

    Returns:
        List of dicts with 'rule_id' and 'text' keys, where 'text' is the looked-up explanation
    """
    rationale: list[dict[str, str]] = []

    for violation in violations:
        rule_id = violation.get("rule_id", "UNKNOWN")
        explanation = RULE_EXPLANATIONS.get(rule_id, f"Rule {rule_id} was violated.")

        rationale.append({"rule_id": rule_id, "text": explanation})

    return rationale
