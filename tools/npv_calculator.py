"""
NPV Calculator & Automation Generator for Stellaris Enhanced Colony AI

Single source of truth: update the economics data below when Stellaris patches,
then run this script to regenerate the automation file with NPV-optimal ordering.

Usage:
    python tools/npv_calculator.py              # Print NPV table
    python tools/npv_calculator.py --generate   # Generate automation .txt file

Formula: NPV = -C₀ + Σ (Rₜ - Uₜ) / (1 + r)^t  for t = 1..T
"""

import sys
import os
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════
# SECTION 1: ECONOMICS DATA (update these when Stellaris patches)
# ══════════════════════════════════════════════════════════════════════════

MARKET_PRICES = {
    "energy": 1.0,
    "minerals": 1.0,
    "food": 1.0,
    "consumer_goods": 2.0,
    "alloys": 4.0,
    "rare_crystals": 10.0,
    "volatile_motes": 10.0,
    "exotic_gases": 10.0,
    "unity": 1.5,
    "research": 2.0,
    "amenities": 0.5,
    "housing": 0.3,
    "trade_value": 1.0,
}

MONTHLY_DISCOUNT_RATE = 0.01  # 1%/month (~12.7% annual)
HORIZON_MONTHS = 120  # 10 years in-game

# Building economics: build_cost, monthly_output, monthly_upkeep
# Update these numbers when Stellaris patches change building stats.
BUILDING_ECONOMICS = {
    # Deposit extractors
    "building_crystal_mines": {
        "build_cost": {"minerals": 200},
        "output": {"rare_crystals": 2},
        "upkeep": {"energy": 1},
    },
    "building_mote_harvesters": {
        "build_cost": {"minerals": 200},
        "output": {"volatile_motes": 2},
        "upkeep": {"energy": 1},
    },
    "building_gas_extractors": {
        "build_cost": {"minerals": 200},
        "output": {"exotic_gases": 2},
        "upkeep": {"energy": 1},
    },
    # Production boosters (percentage-based, using conservative flat estimates)
    "building_mineral_purification_plant": {
        "build_cost": {"minerals": 200},
        "output": {"minerals": 5},
        "upkeep": {"energy": 2},
    },
    "building_energy_grid": {
        "build_cost": {"minerals": 400},
        "output": {"energy": 7},
        "upkeep": {"energy": 2},
    },
    "building_food_processing_facility": {
        "build_cost": {"minerals": 400},
        "output": {"food": 7},
        "upkeep": {"energy": 2},
    },
    # Specialist production
    "building_foundry_1": {
        "build_cost": {"minerals": 400},
        "output": {"alloys": 12},
        "upkeep": {"energy": 2, "minerals": 24},
    },
    "building_factory_1": {
        "build_cost": {"minerals": 400},
        "output": {"consumer_goods": 24},
        "upkeep": {"energy": 2, "minerals": 24},
    },
    "building_research_lab_1": {
        "build_cost": {"minerals": 400},
        "output": {"research": 16},
        "upkeep": {"energy": 2, "consumer_goods": 8},
    },
    # Amenity / pop growth
    "building_holo_theatres": {
        "build_cost": {"minerals": 400},
        "output": {"amenities": 40, "unity": 4},
        "upkeep": {"energy": 2},
    },
    "building_medical_1": {
        "build_cost": {"minerals": 400},
        "output": {"amenities": 20, "housing": 2},
        "upkeep": {"energy": 2},
    },
    # Unity
    "building_bureaucratic_1": {
        "build_cost": {"minerals": 400},
        "output": {"unity": 16},
        "upkeep": {"energy": 2},
    },
    "building_temple": {
        "build_cost": {"minerals": 400},
        "output": {"unity": 16},
        "upkeep": {"energy": 2},
    },
    # Strategic resource plants (synthetic)
    "building_refinery": {
        "build_cost": {"minerals": 500},
        "output": {"exotic_gases": 2},
        "upkeep": {"energy": 3, "minerals": 10},
    },
    "building_chemical_plant": {
        "build_cost": {"minerals": 600},
        "output": {"volatile_motes": 2},
        "upkeep": {"energy": 3, "minerals": 10},
    },
    "building_crystal_plant": {
        "build_cost": {"minerals": 600},
        "output": {"rare_crystals": 2},
        "upkeep": {"energy": 3, "minerals": 10},
    },
    # Capital unique buildings
    "building_embassy": {
        "build_cost": {"minerals": 600, "rare_crystals": 50},
        "output": {"unity": 3, "amenities": 5},
        "upkeep": {"energy": 5, "rare_crystals": 1},
    },
    "building_autochthon_monument": {
        "build_cost": {"minerals": 400},
        "output": {"unity": 5},
        "upkeep": {},
    },
    # Districts (for NPV comparison only)
    "district_mining": {
        "build_cost": {"minerals": 300},
        "output": {"minerals": 24},
        "upkeep": {"energy": 1},
    },
    "district_generator": {
        "build_cost": {"minerals": 300},
        "output": {"energy": 36},
        "upkeep": {"energy": 1},
    },
    "district_farming": {
        "build_cost": {"minerals": 300},
        "output": {"food": 36},
        "upkeep": {"energy": 1},
    },
    "district_city": {
        "build_cost": {"minerals": 500},
        "output": {"housing": 8, "trade_value": 4, "amenities": 2},
        "upkeep": {"energy": 2},
    },
}


# ══════════════════════════════════════════════════════════════════════════
# SECTION 2: NPV ENGINE
# ══════════════════════════════════════════════════════════════════════════

def normalize_cost(resources: dict) -> float:
    return sum(MARKET_PRICES.get(r, 1.0) * amt for r, amt in resources.items())


def compute_npv(building_id: str) -> float:
    econ = BUILDING_ECONOMICS.get(building_id)
    if not econ:
        return 0.0
    c0 = normalize_cost(econ["build_cost"])
    net = normalize_cost(econ["output"]) - normalize_cost(econ["upkeep"])
    r = MONTHLY_DISCOUNT_RATE
    T = HORIZON_MONTHS
    if r == 0:
        return -c0 + net * T
    df = (1 - (1 + r) ** (-T)) / r
    return -c0 + net * df


def compute_payback(building_id: str) -> float:
    econ = BUILDING_ECONOMICS.get(building_id)
    if not econ:
        return float("inf")
    c0 = normalize_cost(econ["build_cost"])
    net = normalize_cost(econ["output"]) - normalize_cost(econ["upkeep"])
    return c0 / net if net > 0 else float("inf")


# Build cost tiers for 2x stockpile triggers
# Maps mineral build cost → scripted trigger name
BUILD_COST_TIERS = {
    200: "eca_can_afford_build_cost_200",
    300: "eca_can_afford_build_cost_300",
    400: "eca_can_afford_build_cost_400",
    500: "eca_can_afford_build_cost_500",
    600: "eca_can_afford_build_cost_600",
}

# Buildings not in BUILDING_ECONOMICS that we know the cost of
KNOWN_BUILD_COSTS = {
    # Unique buildings (400 minerals each)
    "building_embassy": 400,
    "building_autochthon_monument": 400,
    "building_corporate_monument": 400,
    "building_vultaum_reality_computer": 400,
    "building_institute": 400,
    "building_archaeostudies_faculty": 400,
    "building_autocurating_vault": 400,
    "building_citadel_of_faith": 400,
    "building_corporate_vault": 400,
    "building_ministry_production": 400,
    "building_production_center": 400,
    "building_supercomputer": 400,
    "building_robot_assembly_plant": 400,
    # Efficiency/upkeep buildings
    "building_foundry_efficiency_1": 400,
    "building_foundry_upkeep_1": 400,
    "building_factory_efficiency_1": 400,
    "building_factory_upkeep_1": 400,
    "building_research_efficiency_1": 400,
    "building_research_upkeep_1": 400,
    # District capacity upgrades
    "building_mining_districts_1": 400,
    "building_generator_districts_1": 400,
    "building_farming_districts_1": 400,
    # Research labs (specific types)
    "building_engineering_facility_1": 400,
    "building_physics_lab_1": 400,
    "building_biolab_1": 400,
}


def get_build_cost_trigger(building_id: str) -> str:
    """Get the 2x stockpile trigger name for a building, or '' if unknown."""
    # Check BUILDING_ECONOMICS first
    econ = BUILDING_ECONOMICS.get(building_id)
    if econ:
        mineral_cost = econ["build_cost"].get("minerals", 0)
    elif building_id in KNOWN_BUILD_COSTS:
        mineral_cost = KNOWN_BUILD_COSTS[building_id]
    else:
        return ""

    # Round up to nearest tier
    for tier in sorted(BUILD_COST_TIERS.keys()):
        if mineral_cost <= tier:
            return BUILD_COST_TIERS[tier]
    # If higher than all tiers, use the highest
    return BUILD_COST_TIERS[max(BUILD_COST_TIERS.keys())]


# ══════════════════════════════════════════════════════════════════════════
# SECTION 3: AVAILABLE CONDITIONS (Stellaris script blocks)
# These define the `available = { ... }` conditions for each building.
# ══════════════════════════════════════════════════════════════════════════

# -- Gene clinic --
COND_GENE_CLINIC = "free_amenities < 8\nowner = { is_synthetic_empire = no }"
COND_GENE_CLINIC_CAPITAL = "owner = { is_synthetic_empire = no }"

# -- Amenity emergency --
COND_HOLO_LOW = "free_amenities < 3"
COND_HOLO_CAPITAL = "free_amenities < 5"

# -- Foundry --
COND_FOUNDRY_AFFORD = (
    "exists = owner\nowner = { eca_can_afford_foundry_upkeep = yes }"
)
COND_FOUNDRY_DEFICIT = (
    "exists = owner\n"
    "owner = {\n"
    "\teca_has_alloy_deficit = yes\n"
    "\teca_can_afford_foundry_upkeep = yes\n"
    "}"
)
COND_FOUNDRY_CAPITAL = (
    "num_pops > 0\n"
    "exists = owner\n"
    "owner = {\n"
    "\teca_can_afford_foundry_upkeep = yes\n"
    "\teca_has_alloy_deficit = yes\n"
    "}"
)

# -- Factory --
COND_FACTORY_AFFORD = (
    "exists = owner\nowner = { eca_can_afford_factory_upkeep = yes }"
)
COND_FACTORY_DEFICIT = (
    "exists = owner\n"
    "owner = {\n"
    "\teca_has_consumer_goods_deficit = yes\n"
    "\tcountry_uses_consumer_goods = yes\n"
    "\teca_can_afford_factory_upkeep = yes\n"
    "}"
)
COND_FACTORY_CAPITAL = (
    "num_pops > 0\n"
    "exists = owner\n"
    "owner = {\n"
    "\tcountry_uses_consumer_goods = yes\n"
    "\teca_can_afford_factory_upkeep = yes\n"
    "\teca_has_consumer_goods_deficit = yes\n"
    "}"
)

# -- Research --
COND_RESEARCH_AFFORD = (
    "exists = owner\nowner = { eca_can_afford_research_upkeep = yes }"
)

# -- Admin / Temple --
COND_ADMIN = (
    "exists = owner\n"
    "owner = {\n"
    "\tis_spiritualist = no\n"
    "\thas_make_spiritualist_perk = no\n"
    "\teca_can_afford_energy_upkeep = yes\n"
    "}"
)
COND_TEMPLE = (
    "exists = owner\n"
    "owner = {\n"
    "\tOR = {\n"
    "\t\tis_spiritualist = yes\n"
    "\t\thas_make_spiritualist_perk = yes\n"
    "\t}\n"
    "\teca_can_afford_energy_upkeep = yes\n"
    "}"
)

# -- Strategic resource deficits --
COND_GAS_DEFICIT = (
    "exists = owner\n"
    "owner = {\n"
    "\teca_has_exotic_gas_deficit = yes\n"
    "\teca_can_afford_strategic_upkeep = yes\n"
    "}"
)
COND_MOTE_DEFICIT = (
    "exists = owner\n"
    "owner = {\n"
    "\teca_has_volatile_mote_deficit = yes\n"
    "\teca_can_afford_strategic_upkeep = yes\n"
    "}"
)
COND_CRYSTAL_DEFICIT = (
    "exists = owner\n"
    "owner = {\n"
    "\teca_has_rare_crystal_deficit = yes\n"
    "\teca_can_afford_strategic_upkeep = yes\n"
    "}"
)


# ══════════════════════════════════════════════════════════════════════════
# SECTION 4: DESIGNATION CONFIGURATIONS
# Each designation defines districts, zones, and a tiered building list.
#
# Building list format:
#   Each item is either a dict or a list of dicts (for variant groups).
#   Dict keys:
#     "building" : Stellaris building ID (required)
#     "suffix"   : key suffix like "corp", "spir" (default: "")
#     "available" : condition string (default: "" = no condition)
#     "tier"     : int, lower = higher priority (default: 1)
#                  tier 0 = unique (not NPV-sorted, keeps listed order)
#                  tier 1+ = NPV-sorted within same tier
#     "comment"  : optional comment above the building entry
# ══════════════════════════════════════════════════════════════════════════

def b(building, suffix="", available="", tier=1, comment=""):
    """Shorthand to create a building entry dict."""
    return {
        "building": building,
        "suffix": suffix,
        "available": available,
        "tier": tier,
        "comment": comment,
    }


# Helper: common building groups used across designations
def deposit_extractors():
    """Deposit-based strategic resource extractors (NPV=1124 each)."""
    return [
        b("building_crystal_mines", tier=1, comment="Deposit extractor - NPV={npv}"),
        b("building_mote_harvesters", tier=1, comment="Deposit extractor - NPV={npv}"),
        b("building_gas_extractors", tier=1, comment="Deposit extractor - NPV={npv}"),
    ]


def admin_temple_group():
    """Administrative office / temple variant group."""
    return [
        b("building_bureaucratic_1", suffix="admin", available=COND_ADMIN,
          tier=2, comment="Unity - NPV={npv}"),
        b("building_temple", suffix="temple", available=COND_TEMPLE, tier=2),
    ]


def strategic_plants():
    """Synthetic strategic resource plants (deficit-only)."""
    return [
        b("building_refinery", available=COND_GAS_DEFICIT,
          tier=4, comment="Strategic - NPV={npv}, deficit-only"),
        b("building_chemical_plant", available=COND_MOTE_DEFICIT,
          tier=4, comment="Strategic - NPV={npv}, deficit-only"),
        b("building_crystal_plant", available=COND_CRYSTAL_DEFICIT,
          tier=4, comment="Strategic - NPV={npv}, deficit-only"),
    ]


DESIGNATIONS = {
    # ── CAPITAL ──
    "capital": {
        "prio_districts": [
            "district_city",
            "district_arcology_housing",
            "district_rw_city",
            "district_hab_housing",
            "district_generator",
            "district_generator_uncapped",
            "district_mining",
            "district_mining_uncapped",
            "district_farming",
            "district_farming_uncapped",
        ],
        "prio_zones": [
            "zone_industrial",
            "zone_research_unity",
            "zone_foundry",
            "zone_energy",
            "zone_food",
            "zone_minerals",
        ],
        "buildings": [
            # Tier 0: Unique (never NPV-sorted)
            b("building_embassy", tier=0, comment="Unique - diplomatic weight"),
            b("building_autochthon_monument", tier=0, comment="Unique - free unity"),
            b("building_corporate_monument", suffix="corp", tier=0),
            b("building_vultaum_reality_computer", tier=0, comment="Unique - precursor"),
            b("building_institute", tier=0, comment="Unique - research boost"),
            b("building_archaeostudies_faculty", tier=0),
            b("building_autocurating_vault", tier=0),
            b("building_citadel_of_faith", suffix="spir", tier=0),
            b("building_corporate_vault", suffix="corp", tier=0),
            # Tier 1: Production (NPV-sorted)
            b("building_foundry_1", available=COND_FOUNDRY_CAPITAL,
              tier=1, comment="Alloy foundry - NPV={npv}, deficit only"),
            b("building_factory_1", available=COND_FACTORY_CAPITAL,
              tier=1, comment="CG factory - NPV={npv}, deficit only"),
            # Admin/temple variant group
            *admin_temple_group(),
            b("building_research_lab_1", available=COND_RESEARCH_AFFORD,
              tier=2, comment="Research lab - NPV={npv}"),
            # Tier 3: Support
            b("building_medical_1", available=COND_GENE_CLINIC_CAPITAL,
              tier=3, comment="Gene clinic - NPV={npv} + pop growth"),
            b("building_holo_theatres", available=COND_HOLO_CAPITAL,
              tier=3, comment="Holo theatre - NPV={npv}, amenity emergency"),
            # Tier 4: Strategic
            *strategic_plants(),
        ],
    },

    # ── MINING ──
    "mining": {
        "prio_districts": [
            "district_mining",
            "district_mining_uncapped",
        ],
        "prio_zones": [
            "zone_minerals",
        ],
        "buildings": [
            *deposit_extractors(),
            # Tier 1: On-designation capacity
            b("building_mining_districts_1", tier=1,
              comment="District capacity upgrade"),
            # Tier 2: Support
            b("building_medical_1", available=COND_GENE_CLINIC,
              tier=2, comment="Gene clinic - NPV={npv} + pop growth"),
            # Tier 2: Off-designation (deficit)
            b("building_foundry_1", available=COND_FOUNDRY_DEFICIT,
              tier=2, comment="Off-designation - NPV={npv}, deficit-only"),
            b("building_factory_1", available=COND_FACTORY_DEFICIT,
              tier=2, comment="Off-designation - NPV={npv}, deficit-only"),
            *admin_temple_group(),
            # Tier 3: Production booster (low NPV, scales with workers)
            b("building_mineral_purification_plant", tier=3,
              comment="Production booster - NPV={npv} (scales with miner count)"),
            b("building_holo_theatres", available=COND_HOLO_LOW,
              tier=3, comment="Amenity emergency - NPV={npv}"),
            # Tier 4: Strategic
            *strategic_plants(),
        ],
    },

    # ── GENERATOR ──
    "generator": {
        "prio_districts": [
            "district_generator",
            "district_generator_uncapped",
        ],
        "prio_zones": [
            "zone_energy",
        ],
        "buildings": [
            *deposit_extractors(),
            b("building_generator_districts_1", tier=1,
              comment="District capacity upgrade"),
            b("building_medical_1", available=COND_GENE_CLINIC,
              tier=2, comment="Gene clinic - NPV={npv} + pop growth"),
            b("building_foundry_1", available=COND_FOUNDRY_DEFICIT,
              tier=2, comment="Off-designation - NPV={npv}, deficit-only"),
            b("building_factory_1", available=COND_FACTORY_DEFICIT,
              tier=2, comment="Off-designation - NPV={npv}, deficit-only"),
            *admin_temple_group(),
            b("building_energy_grid", tier=3,
              comment="Production booster - NPV={npv} (scales with technician count)"),
            b("building_holo_theatres", available=COND_HOLO_LOW,
              tier=3, comment="Amenity emergency - NPV={npv}"),
            *strategic_plants(),
        ],
    },

    # ── FARMING ──
    "farming": {
        "prio_districts": [
            "district_farming",
            "district_farming_uncapped",
        ],
        "prio_zones": [
            "zone_food",
        ],
        "buildings": [
            *deposit_extractors(),
            b("building_farming_districts_1", tier=1,
              comment="District capacity upgrade"),
            b("building_medical_1", available=COND_GENE_CLINIC,
              tier=2, comment="Gene clinic - NPV={npv} + pop growth"),
            b("building_foundry_1", available=COND_FOUNDRY_DEFICIT,
              tier=2, comment="Off-designation - NPV={npv}, deficit-only"),
            b("building_factory_1", available=COND_FACTORY_DEFICIT,
              tier=2, comment="Off-designation - NPV={npv}, deficit-only"),
            *admin_temple_group(),
            b("building_food_processing_facility", tier=3,
              comment="Production booster - NPV={npv} (scales with farmer count)"),
            b("building_holo_theatres", available=COND_HOLO_LOW,
              tier=3, comment="Amenity emergency - NPV={npv}"),
            *strategic_plants(),
        ],
    },

    # ── FOUNDRY ──
    "foundry": {
        "prio_districts": [
            "district_arcology_housing",
            "district_rw_city",
            "district_city",
        ],
        "prio_zones": [
            "zone_foundry",
        ],
        "buildings": [
            # Tier 0: Unique production boosters
            b("building_ministry_production", tier=0, comment="Unique production booster"),
            b("building_production_center", tier=0),
            b("building_foundry_efficiency_1", tier=0),
            b("building_foundry_upkeep_1", tier=0),
            # Tier 1: Core production
            b("building_foundry_1", available=COND_FOUNDRY_AFFORD,
              tier=1, comment="Core foundry - NPV={npv}"),
            # Tier 2: Support
            b("building_medical_1", available=COND_GENE_CLINIC,
              tier=2, comment="Gene clinic - NPV={npv} + pop growth"),
            *admin_temple_group(),
            b("building_holo_theatres", available=COND_HOLO_LOW,
              tier=2, comment="Amenity emergency - NPV={npv}"),
            # Tier 3: Off-designation (deficit)
            b("building_factory_1", available=COND_FACTORY_DEFICIT,
              tier=3, comment="Off-designation - NPV={npv}, deficit-only"),
            # Tier 4: Strategic
            b("building_chemical_plant", available=COND_MOTE_DEFICIT,
              tier=4, comment="Strategic - NPV={npv}, foundries use motes"),
            b("building_crystal_plant", available=COND_CRYSTAL_DEFICIT, tier=4),
            b("building_refinery", available=COND_GAS_DEFICIT, tier=4),
        ],
    },

    # ── FACTORY ──
    "factory": {
        "prio_districts": [
            "district_arcology_housing",
            "district_rw_city",
            "district_city",
        ],
        "prio_zones": [
            "zone_factory",
        ],
        "buildings": [
            b("building_ministry_production", tier=0, comment="Unique production booster"),
            b("building_production_center", tier=0),
            b("building_factory_efficiency_1", tier=0),
            b("building_factory_upkeep_1", tier=0),
            b("building_factory_1", available=COND_FACTORY_AFFORD,
              tier=1, comment="Core factory - NPV={npv}"),
            b("building_medical_1", available=COND_GENE_CLINIC,
              tier=2, comment="Gene clinic - NPV={npv} + pop growth"),
            *admin_temple_group(),
            b("building_holo_theatres", available=COND_HOLO_LOW,
              tier=2, comment="Amenity emergency - NPV={npv}"),
            b("building_foundry_1", available=COND_FOUNDRY_DEFICIT,
              tier=3, comment="Off-designation - NPV={npv}, deficit-only"),
            b("building_crystal_plant", available=COND_CRYSTAL_DEFICIT,
              tier=4, comment="Strategic - NPV={npv}, factories use crystals"),
            b("building_chemical_plant", available=COND_MOTE_DEFICIT, tier=4),
            b("building_refinery", available=COND_GAS_DEFICIT, tier=4),
        ],
    },

    # ── RESEARCH ──
    "research": {
        "prio_districts": [
            "district_arcology_housing",
            "district_rw_city",
            "district_hab_science",
            "district_hab_housing",
            "district_city",
        ],
        "prio_zones": [
            "zone_research",
        ],
        "buildings": [
            # Tier 0: Unique buildings
            b("building_vultaum_reality_computer", tier=0, comment="Unique - precursor"),
            b("building_institute", tier=0, comment="Unique - research boost"),
            b("building_supercomputer", tier=0),
            b("building_archaeostudies_faculty", tier=0),
            b("building_research_efficiency_1", tier=0, comment="Unique - efficiency"),
            b("building_research_upkeep_1", tier=0),
            # Tier 1: Core research (specific labs)
            b("building_engineering_facility_1", available=COND_RESEARCH_AFFORD,
              tier=1, comment="Stackable research - NPV={npv}"),
            b("building_physics_lab_1", available=COND_RESEARCH_AFFORD, tier=1),
            b("building_biolab_1", available=COND_RESEARCH_AFFORD, tier=1),
            # Tier 2: Support
            b("building_medical_1", available=COND_GENE_CLINIC,
              tier=2, comment="Gene clinic - NPV={npv} + pop growth"),
            *admin_temple_group(),
            b("building_holo_theatres", available=COND_HOLO_LOW,
              tier=2, comment="Amenity emergency - NPV={npv}"),
            # Tier 4: Strategic
            b("building_refinery", available=COND_GAS_DEFICIT,
              tier=4, comment="Strategic - NPV={npv}, research uses gas"),
            b("building_crystal_plant", available=COND_CRYSTAL_DEFICIT, tier=4),
            b("building_chemical_plant", available=COND_MOTE_DEFICIT, tier=4),
        ],
    },

    # ── INDUSTRIAL ──
    "industrial": {
        "prio_districts": [
            "district_arcology_housing",
            "district_rw_city",
            "district_city",
        ],
        "prio_zones": [
            "zone_industrial",
        ],
        "buildings": [
            b("building_ministry_production", tier=0, comment="Unique production booster"),
            b("building_production_center", tier=0),
            b("building_foundry_efficiency_1", tier=0),
            b("building_factory_efficiency_1", tier=0),
            b("building_foundry_upkeep_1", tier=0),
            b("building_factory_upkeep_1", tier=0),
            # Tier 1: Core production (NPV-sorted)
            b("building_foundry_1", available=COND_FOUNDRY_AFFORD,
              tier=1, comment="Core foundry - NPV={npv}"),
            b("building_factory_1", available=COND_FACTORY_AFFORD,
              tier=1, comment="Core factory - NPV={npv}"),
            # Tier 2: Support
            b("building_medical_1", available=COND_GENE_CLINIC,
              tier=2, comment="Gene clinic - NPV={npv} + pop growth"),
            *admin_temple_group(),
            b("building_holo_theatres", available=COND_HOLO_LOW,
              tier=2, comment="Amenity emergency - NPV={npv}"),
            # Tier 4: Strategic
            *strategic_plants(),
        ],
    },
}


# ══════════════════════════════════════════════════════════════════════════
# SECTION 5: CODE GENERATION
# ══════════════════════════════════════════════════════════════════════════

def sort_buildings(buildings: list) -> list:
    """Sort buildings by tier, then by NPV within each tier (except tier 0)."""
    # Identify variant groups: consecutive buildings with same tier and suffix
    # Group admin+temple as variants (they share a slot)
    result = []

    # Separate by tier
    from itertools import groupby
    for tier, group in groupby(buildings, key=lambda x: x["tier"]):
        tier_buildings = list(group)
        if tier == 0:
            # Unique buildings: keep original order
            result.extend(tier_buildings)
        else:
            # Sort by NPV descending within tier
            tier_buildings.sort(
                key=lambda x: compute_npv(x["building"]), reverse=True
            )
            result.extend(tier_buildings)

    return result


def format_available(condition: str, indent: int) -> str:
    """Format an available block with proper indentation."""
    prefix = "\t" * indent
    lines = condition.split("\n")
    formatted = "\n".join(prefix + line for line in lines)
    return f"{prefix[:-1]}available = {{\n{formatted}\n{prefix[:-1]}}}"


def generate_building_block(entry: dict, key_num: int, indent: int = 2) -> str:
    """Generate a single building entry in Stellaris script format."""
    prefix = "\t" * indent
    suffix = f"_{entry['suffix']}" if entry.get("suffix") else ""
    key = f"{key_num}{suffix}"

    lines = []

    # Add comment if present
    if entry.get("comment"):
        npv_val = compute_npv(entry["building"])
        comment = entry["comment"].format(npv=f"{npv_val:.0f}")
        lines.append(f"{prefix}# {comment}")

    lines.append(f"{prefix}{key} = {{")
    lines.append(f"{prefix}\tbuilding = {entry['building']}")

    # Build the available block: combine explicit conditions + 2x stockpile check
    cost_trigger = get_build_cost_trigger(entry["building"])
    has_conditions = bool(entry.get("available"))
    has_cost_trigger = bool(cost_trigger)

    if has_conditions or has_cost_trigger:
        lines.append(f"{prefix}\tavailable = {{")
        if has_conditions:
            for cond_line in entry["available"].split("\n"):
                lines.append(f"{prefix}\t\t{cond_line}")
        if has_cost_trigger:
            # Stockpile check is on owner (country scope)
            # Skip 'exists = owner' if already present in conditions
            if not has_conditions or "exists = owner" not in entry["available"]:
                lines.append(f"{prefix}\t\texists = owner")
            lines.append(f"{prefix}\t\towner = {{ {cost_trigger} = yes }}")
        lines.append(f"{prefix}\t}}")

    lines.append(f"{prefix}}}")
    return "\n".join(lines)


def generate_designation(name: str, config: dict) -> str:
    """Generate a complete automation block for one designation."""
    lines = []
    lines.append(f"automate_eca_{name} = {{")
    lines.append(f'\tcategory = "planet_automation_designation_construction"')
    lines.append("")
    lines.append(f"\tavailable = {{")
    lines.append(f"\t\thas_designation = col_eca_{name}")
    lines.append(f"\t}}")
    lines.append("")

    # prio_districts
    if config.get("prio_districts_comment"):
        lines.append(f"\t# {config['prio_districts_comment']}")
    lines.append(f"\tprio_districts = {{")
    for d in config["prio_districts"]:
        lines.append(f"\t\t{d}")
    lines.append(f"\t}}")
    lines.append("")

    # prio_zones
    lines.append(f"\tprio_zones = {{")
    for z in config["prio_zones"]:
        lines.append(f"\t\t{z}")
    lines.append(f"\t}}")
    lines.append("")

    # buildings
    sorted_buildings = sort_buildings(config["buildings"])
    lines.append(f"\tbuildings = {{")

    # Assign key numbers
    # Variant groups (admin/temple) share a number
    key_num = 0
    prev_suffix = None
    for i, entry in enumerate(sorted_buildings):
        suffix = entry.get("suffix", "")

        # Determine if this is a variant of the previous entry
        is_variant = False
        if suffix and i > 0:
            prev = sorted_buildings[i - 1]
            prev_s = prev.get("suffix", "")
            # admin+temple are always variants of each other
            if (suffix in ("admin", "temple") and
                    prev_s in ("admin", "temple")):
                is_variant = True
            # corp/spir variants share number with the entry above
            elif suffix in ("corp", "spir") and not prev_s:
                is_variant = True
            elif prev_s in ("corp", "spir") and suffix in ("corp", "spir"):
                is_variant = True

        if not is_variant:
            key_num += 1

        block = generate_building_block(entry, key_num, indent=2)
        lines.append("")
        lines.append(block)

    lines.append(f"\t}}")
    lines.append(f"}}")

    return "\n".join(lines)


def generate_automation_file() -> str:
    """Generate the complete 01_eca_automation.txt file."""
    sections = []
    sections.append(
        "# Enhanced Colony Automation AI - Automation for new ECA designations\n"
        "# AUTO-GENERATED by tools/npv_calculator.py — do not edit manually.\n"
        f"# NPV parameters: r={MONTHLY_DISCOUNT_RATE*100:.1f}%/month, "
        f"T={HORIZON_MONTHS} months\n"
        "# Uses 2x affordability buffer: only build if surplus >= 2x upkeep cost."
    )

    for name in [
        "capital", "mining", "generator", "farming",
        "foundry", "factory", "research", "industrial",
    ]:
        config = DESIGNATIONS[name]
        header = f"# ===== ENHANCED {name.upper()} ====="
        sections.append(f"\n{header}\n")
        sections.append(generate_designation(name, config))

    return "\n".join(sections) + "\n"


# ══════════════════════════════════════════════════════════════════════════
# SECTION 6: NPV TABLE DISPLAY
# ══════════════════════════════════════════════════════════════════════════

def print_npv_table():
    """Print NPV rankings table."""
    results = []
    for name, econ in BUILDING_ECONOMICS.items():
        score = compute_npv(name)
        payback = compute_payback(name)
        net = normalize_cost(econ["output"]) - normalize_cost(econ["upkeep"])
        results.append({
            "name": name,
            "build_cost_ec": normalize_cost(econ["build_cost"]),
            "net_monthly_ec": net,
            "npv": score,
            "payback": payback,
        })

    results.sort(key=lambda x: x["npv"], reverse=True)

    print(f"{'=' * 100}")
    print(f"Stellaris Building/District NPV Rankings")
    print(f"r={MONTHLY_DISCOUNT_RATE*100:.1f}%/month | T={HORIZON_MONTHS}mo")
    print(f"{'=' * 100}")
    print(f"{'Rank':<5} {'Name':<45} {'Build(EC)':<10} "
          f"{'Net/mo':<8} {'NPV':<10} {'Payback'}")
    print(f"{'-' * 100}")

    for i, r in enumerate(results, 1):
        pb = f"{r['payback']:.0f}mo" if r["payback"] < float("inf") else "never"
        print(f"{i:<5} {r['name']:<45} {r['build_cost_ec']:<10.0f} "
              f"{r['net_monthly_ec']:<8.1f} {r['npv']:<10.0f} {pb}")


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if "--generate" in sys.argv:
        output = generate_automation_file()

        # Write to the mod directory
        script_dir = Path(__file__).resolve().parent
        mod_dir = script_dir.parent
        out_path = mod_dir / "common" / "colony_automation" / "01_eca_automation.txt"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")

        print(f"Generated: {out_path}")
        print(f"Buildings per designation:")
        for name, config in DESIGNATIONS.items():
            print(f"  {name}: {len(config['buildings'])} buildings")
    else:
        print_npv_table()
        print(f"\nRun with --generate to output 01_eca_automation.txt")
