"""
Parser-based unit tests for Enhanced Colony Automation AI.

Tests all automation rules by parsing the actual mod files and evaluating
conditions against simulated planet/empire states.  Catches the exact class
of bugs found during manual playtesting:

  - Robot assembly firing with unemployed pops
  - Generator district not building with unemployed pops
  - Holo theatre blocked by affordability checks
  - Factory world building research labs instead of housing
  - Research world blocked by 0 CG surplus
  - Capital not building generator districts during energy deficit
  - Gene clinic firing on empty planets

Run:  pytest tools/test_automation.py -v
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from clausewitz_parser import (
    EmpireState,
    EvalError,
    ParsedBlock,
    PlanetState,
    evaluate_available,
    find_blocks,
    get_prio_districts,
    get_prio_zones,
    get_all_automation_blocks,
    get_value,
    parse_file,
    would_build,
)

# ─── Fixtures: parse the real mod files once ─────────────────────────────────

MOD_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def automation_blocks() -> dict[str, ParsedBlock]:
    """Parse 01_eca_automation.txt and return all automation blocks."""
    path = MOD_ROOT / "common" / "colony_automation" / "01_eca_automation.txt"
    parsed = parse_file(path)
    return get_all_automation_blocks(parsed)


@pytest.fixture(scope="session")
def exception_blocks() -> dict[str, ParsedBlock]:
    """Parse 01_eca_exceptions.txt and return all automation blocks."""
    path = MOD_ROOT / "common" / "colony_automation_exceptions" / "01_eca_exceptions.txt"
    parsed = parse_file(path)
    return get_all_automation_blocks(parsed)


@pytest.fixture(scope="session")
def trigger_blocks() -> ParsedBlock:
    """Parse 99_eca_scripted_triggers.txt."""
    path = MOD_ROOT / "common" / "scripted_triggers" / "99_eca_scripted_triggers.txt"
    return parse_file(path)


# ─── Helper: default healthy empire ─────────────────────────────────────────


def healthy_empire(**overrides) -> EmpireState:
    """Create an empire with comfortable surpluses (no deficits)."""
    defaults = dict(
        is_regular_empire=True,
        is_gestalt=False,
        is_synthetic_empire=False,
        is_spiritualist=False,
        monthly_income={
            "minerals": 50, "energy": 30, "food": 20,
            "alloys": 10, "consumer_goods": 10,
            "rare_crystals": 2, "volatile_motes": 2, "exotic_gases": 2,
        },
        stockpiles={
            "minerals": 2000, "energy": 1000, "food": 500,
            "alloys": 500, "consumer_goods": 300,
        },
    )
    defaults.update(overrides)
    return EmpireState(**defaults)


def broke_empire(**overrides) -> EmpireState:
    """Create an empire with low resources (below affordability thresholds)."""
    defaults = dict(
        is_regular_empire=True,
        is_gestalt=False,
        monthly_income={
            "minerals": 2, "energy": 1, "food": 1,
            "alloys": 1, "consumer_goods": 1,
            "rare_crystals": 0, "volatile_motes": 0, "exotic_gases": 0,
        },
        stockpiles={
            "minerals": 100, "energy": 50, "food": 50,
            "alloys": 20, "consumer_goods": 20,
        },
    )
    defaults.update(overrides)
    return EmpireState(**defaults)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 1: Parser sanity
# ═══════════════════════════════════════════════════════════════════════════════


class TestParserSanity:
    """Verify the parser loads all expected blocks from the mod files."""

    def test_automation_file_has_all_designations(self, automation_blocks):
        expected = {
            "automate_eca_capital", "automate_eca_mining", "automate_eca_generator",
            "automate_eca_farming", "automate_eca_foundry", "automate_eca_factory",
            "automate_eca_research", "automate_eca_industrial",
        }
        assert expected.issubset(set(automation_blocks.keys())), \
            f"Missing blocks: {expected - set(automation_blocks.keys())}"

    def test_exceptions_file_has_key_blocks(self, exception_blocks):
        expected = {
            "automate_eca_robot_assembly", "automate_eca_gene_clinic",
            "automate_eca_holo_theatre",
            "automate_eca_stability_precinct", "automate_eca_stability_stronghold",
            "automate_eca_proactive_mining", "automate_eca_proactive_generator",
            "automate_eca_proactive_farming",
            "automate_eca_proactive_foundry", "automate_eca_proactive_factory",
            "automate_eca_proactive_research", "automate_eca_proactive_industrial",
            "automate_eca_proactive_capital",
            "automate_eca_deficit_alloys", "automate_eca_deficit_consumer_goods",
            "automate_eca_deficit_energy", "automate_eca_deficit_minerals",
            "automate_eca_deficit_food",
        }
        assert expected.issubset(set(exception_blocks.keys())), \
            f"Missing blocks: {expected - set(exception_blocks.keys())}"

    def test_all_exception_blocks_have_emergency_flag(self, exception_blocks):
        """Every exception block should have emergency = yes."""
        for name, block in exception_blocks.items():
            emergency = get_value(block, "emergency")
            assert emergency is True, f"{name} missing emergency = yes"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 2: Bug regression — Robot assembly with unemployed pops
# ═══════════════════════════════════════════════════════════════════════════════


class TestRobotAssembly:
    """Verify robot assembly does NOT fire when pops are unemployed."""

    def test_no_build_with_unemployed_pops(self, exception_blocks):
        """BUG: Robot assembly was building despite 10 unemployed pops."""
        planet = PlanetState(
            designation="col_eca_mining",
            free_building_slots=2,
            num_pops=15,
            unemployed_pops=10,
            can_assemble_robot=True,
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_robot_assembly"]
        assert not evaluate_available(block, planet), \
            "Robot assembly should NOT fire with unemployed pops"

    def test_builds_with_no_unemployment(self, exception_blocks):
        """Robot assembly should fire when all pops are employed."""
        planet = PlanetState(
            designation="col_eca_mining",
            free_building_slots=2,
            num_pops=10,
            unemployed_pops=0,
            can_assemble_robot=True,
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_robot_assembly"]
        assert evaluate_available(block, planet)

    def test_no_build_on_empty_planet(self, exception_blocks):
        """BUG: vacuous truth — NOT { any_owned_pop_group = { is_unemployed } }
        is TRUE on 0-pop planets. The num_pops > 0 guard must catch this."""
        planet = PlanetState(
            designation="col_eca_capital",
            free_building_slots=5,
            num_pops=0,
            unemployed_pops=0,
            can_assemble_robot=True,
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_robot_assembly"]
        assert not evaluate_available(block, planet), \
            "Robot assembly should NOT fire on empty planet"

    def test_no_build_when_robots_outlawed(self, exception_blocks):
        planet = PlanetState(
            designation="col_eca_mining",
            free_building_slots=2,
            num_pops=10,
            unemployed_pops=0,
            can_assemble_robot=True,
            owner=healthy_empire(policy_flags={"robots_outlawed"}),
        )
        block = exception_blocks["automate_eca_robot_assembly"]
        assert not evaluate_available(block, planet)

    def test_no_build_without_alloy_surplus(self, exception_blocks):
        """Requires 4+ alloy surplus (2x roboticist upkeep)."""
        empire = healthy_empire()
        empire.monthly_income["alloys"] = 2  # below 4 threshold
        planet = PlanetState(
            designation="col_eca_mining",
            free_building_slots=2,
            num_pops=10,
            unemployed_pops=0,
            can_assemble_robot=True,
            owner=empire,
        )
        block = exception_blocks["automate_eca_robot_assembly"]
        assert not evaluate_available(block, planet)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 3: Bug regression — Gene clinic with unemployed pops
# ═══════════════════════════════════════════════════════════════════════════════


class TestGeneClinic:
    """Gene clinic should not fire with unemployed pops or on empty planets."""

    def test_no_build_with_unemployed_pops(self, exception_blocks):
        planet = PlanetState(
            designation="col_eca_farming",
            free_building_slots=2,
            num_pops=8,
            unemployed_pops=3,
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_gene_clinic"]
        assert not evaluate_available(block, planet)

    def test_no_build_on_empty_planet(self, exception_blocks):
        planet = PlanetState(
            designation="col_eca_capital",
            free_building_slots=5,
            num_pops=0,
            unemployed_pops=0,
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_gene_clinic"]
        assert not evaluate_available(block, planet)

    def test_builds_normally(self, exception_blocks):
        planet = PlanetState(
            designation="col_eca_capital",
            free_building_slots=2,
            num_pops=10,
            unemployed_pops=0,
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_gene_clinic"]
        assert evaluate_available(block, planet)

    def test_no_build_for_synthetic_empire(self, exception_blocks):
        planet = PlanetState(
            designation="col_eca_capital",
            free_building_slots=2,
            num_pops=10,
            unemployed_pops=0,
            owner=healthy_empire(is_synthetic_empire=True),
        )
        block = exception_blocks["automate_eca_gene_clinic"]
        assert not evaluate_available(block, planet)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 4: Bug regression — Holo theatre blocked by affordability
# ═══════════════════════════════════════════════════════════════════════════════


class TestHoloTheatreEmergency:
    """Holo theatre should build when amenities < 0, regardless of economy."""

    def test_builds_when_broke_and_amenities_negative(self, exception_blocks):
        """BUG: Holo theatre was blocked by eca_can_afford_build_cost_400
        even with negative amenities."""
        planet = PlanetState(
            designation="col_eca_factory",
            free_building_slots=1,
            free_amenities=-5,
            num_pops=20,
            owner=broke_empire(),
        )
        block = exception_blocks["automate_eca_holo_theatre"]
        assert evaluate_available(block, planet), \
            "Holo theatre MUST build when amenities are negative, even if broke"

    def test_does_not_build_with_positive_amenities(self, exception_blocks):
        """Should only fire when free_amenities < 0."""
        planet = PlanetState(
            designation="col_eca_factory",
            free_building_slots=1,
            free_amenities=5,
            num_pops=20,
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_holo_theatre"]
        assert not evaluate_available(block, planet)

    def test_does_not_build_for_gestalt(self, exception_blocks):
        """Gestalt empires don't use holo theatres."""
        planet = PlanetState(
            designation="col_eca_mining",
            free_building_slots=1,
            free_amenities=-5,
            num_pops=10,
            owner=healthy_empire(is_regular_empire=True, is_gestalt=True),
        )
        block = exception_blocks["automate_eca_holo_theatre"]
        assert not evaluate_available(block, planet)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 5: Bug regression — Precinct/stronghold bypasses affordability
# ═══════════════════════════════════════════════════════════════════════════════


class TestStabilityEmergency:
    """Precinct and stronghold should bypass affordability checks."""

    def test_precinct_builds_when_broke(self, exception_blocks):
        planet = PlanetState(
            designation="col_eca_mining",
            free_building_slots=1,
            num_pops=15,
            planet_stability=40,
            buildings={},
            forbidden_jobs=set(),
            owner=broke_empire(),
        )
        block = exception_blocks["automate_eca_stability_precinct"]
        assert evaluate_available(block, planet), \
            "Precinct should build at low stability even when broke"

    def test_stronghold_builds_when_broke(self, exception_blocks):
        planet = PlanetState(
            designation="col_eca_mining",
            free_building_slots=1,
            num_pops=15,
            planet_stability=40,
            buildings={},
            owner=broke_empire(),
        )
        block = exception_blocks["automate_eca_stability_stronghold"]
        assert evaluate_available(block, planet)

    def test_precinct_caps_at_one(self, exception_blocks):
        """Should not build second precinct unless stability < 25."""
        planet = PlanetState(
            designation="col_eca_mining",
            free_building_slots=1,
            num_pops=15,
            planet_stability=40,
            buildings={"building_precinct_house": 1},
            forbidden_jobs=set(),
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_stability_precinct"]
        assert not evaluate_available(block, planet), \
            "Should cap at 1 precinct when stability > 25"

    def test_precinct_allows_second_at_critical_stability(self, exception_blocks):
        planet = PlanetState(
            designation="col_eca_mining",
            free_building_slots=1,
            num_pops=15,
            planet_stability=20,
            buildings={"building_precinct_house": 1},
            forbidden_jobs=set(),
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_stability_precinct"]
        assert evaluate_available(block, planet), \
            "Should allow second precinct at stability < 25"

    def test_no_precinct_at_high_stability(self, exception_blocks):
        planet = PlanetState(
            designation="col_eca_mining",
            free_building_slots=1,
            num_pops=15,
            planet_stability=70,
            buildings={},
            forbidden_jobs=set(),
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_stability_precinct"]
        assert not evaluate_available(block, planet)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 6: Bug regression — Generator district not building with unemployed
# ═══════════════════════════════════════════════════════════════════════════════


class TestProactiveDistricts:
    """Proactive district blocks should build when pops have no matching jobs."""

    def test_generator_builds_with_unemployed_and_no_tech_jobs(self, exception_blocks):
        """BUG: Generator district wouldn't build despite 2 unemployed pops
        with no technician jobs available."""
        planet = PlanetState(
            designation="col_eca_generator",
            free_district_slots=3,
            num_pops=10,
            unemployed_pops=2,
            available_jobs={},  # no technician jobs open
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_proactive_generator"]
        assert evaluate_available(block, planet), \
            "Generator district should build when no technician jobs exist"

    def test_generator_builds_during_energy_deficit(self, exception_blocks):
        """Deficit-reactive: build even if technician jobs exist."""
        empire = healthy_empire()
        empire.monthly_income["energy"] = 2  # below 5 threshold
        planet = PlanetState(
            designation="col_eca_generator",
            free_district_slots=3,
            num_pops=10,
            available_jobs={"technician": 1},
            owner=empire,
        )
        block = exception_blocks["automate_eca_proactive_generator"]
        assert evaluate_available(block, planet)

    def test_generator_no_build_with_jobs_and_no_deficit(self, exception_blocks):
        """Don't over-build: if technician jobs exist and no deficit, skip."""
        planet = PlanetState(
            designation="col_eca_generator",
            free_district_slots=3,
            num_pops=10,
            available_jobs={"technician": 2},
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_proactive_generator"]
        assert not evaluate_available(block, planet)

    def test_mining_builds_with_unemployed_no_miner_jobs(self, exception_blocks):
        planet = PlanetState(
            designation="col_eca_mining",
            free_district_slots=3,
            num_pops=10,
            unemployed_pops=2,
            available_jobs={},
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_proactive_mining"]
        assert evaluate_available(block, planet)

    def test_farming_builds_with_food_deficit(self, exception_blocks):
        empire = healthy_empire()
        empire.monthly_income["food"] = 1  # below 3 threshold
        planet = PlanetState(
            designation="col_eca_farming",
            free_district_slots=3,
            num_pops=10,
            available_jobs={"farmer": 1},
            owner=empire,
        )
        block = exception_blocks["automate_eca_proactive_farming"]
        assert evaluate_available(block, planet)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 7: Bug regression — Research blocked by 0 CG surplus
# ═══════════════════════════════════════════════════════════════════════════════


class TestProactiveSpecialist:
    """Specialist zone blocks should bypass upkeep when pops are unemployed."""

    def test_research_builds_with_unemployed_and_zero_cg(self, exception_blocks):
        """BUG: Research zone wouldn't build despite unemployed pops because
        eca_can_afford_research_upkeep requires CG >= 10."""
        empire = healthy_empire()
        empire.monthly_income["consumer_goods"] = 0  # below 10 threshold
        planet = PlanetState(
            designation="col_eca_research",
            free_district_slots=3,
            num_pops=10,
            unemployed_pops=3,
            available_jobs={},
            owner=empire,
        )
        block = exception_blocks["automate_eca_proactive_research"]
        assert evaluate_available(block, planet), \
            "Research zone should build when pops are unemployed, even with 0 CG surplus"

    def test_research_blocked_without_unemployment_and_low_cg(self, exception_blocks):
        """When no unemployment, upkeep check should still apply."""
        empire = healthy_empire()
        empire.monthly_income["consumer_goods"] = 5  # below 10 threshold
        planet = PlanetState(
            designation="col_eca_research",
            free_district_slots=3,
            num_pops=10,
            unemployed_pops=0,
            available_jobs={},  # no researcher jobs
            owner=empire,
        )
        block = exception_blocks["automate_eca_proactive_research"]
        assert not evaluate_available(block, planet), \
            "Research zone should NOT build without unemployment if CG < 10"

    def test_foundry_builds_with_unemployed_low_minerals(self, exception_blocks):
        """Foundry zone should bypass upkeep check when pops are unemployed."""
        empire = healthy_empire()
        empire.monthly_income["minerals"] = 5  # below 12 threshold
        planet = PlanetState(
            designation="col_eca_foundry",
            free_district_slots=3,
            num_pops=10,
            unemployed_pops=2,
            available_jobs={},
            owner=empire,
        )
        block = exception_blocks["automate_eca_proactive_foundry"]
        assert evaluate_available(block, planet)

    def test_factory_builds_with_unemployed_low_minerals(self, exception_blocks):
        empire = healthy_empire()
        empire.monthly_income["minerals"] = 5
        planet = PlanetState(
            designation="col_eca_factory",
            free_district_slots=3,
            num_pops=10,
            unemployed_pops=2,
            available_jobs={},
            owner=empire,
        )
        block = exception_blocks["automate_eca_proactive_factory"]
        assert evaluate_available(block, planet)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 8: Bug regression — Capital not building resource districts
# ═══════════════════════════════════════════════════════════════════════════════


class TestCapitalProactive:
    """Capital proactive block should build resource districts during deficit."""

    def test_capital_builds_during_energy_deficit(self, exception_blocks):
        """BUG: Capital had no resource districts in prio_districts."""
        empire = healthy_empire()
        empire.monthly_income["energy"] = 2  # below 5 = deficit
        planet = PlanetState(
            designation="col_eca_capital",
            free_district_slots=5,
            num_pops=20,
            available_jobs={"physicist": 1},  # has some jobs open
            owner=empire,
        )
        block = exception_blocks["automate_eca_proactive_capital"]
        # The block should fire because of energy deficit
        assert evaluate_available(block, planet)
        # And should include generator districts in prio list
        districts = get_prio_districts(block)
        assert "district_generator" in districts

    def test_capital_prio_districts_include_resources(self, exception_blocks):
        block = exception_blocks["automate_eca_proactive_capital"]
        districts = get_prio_districts(block)
        assert "district_generator" in districts
        assert "district_mining" in districts
        assert "district_farming" in districts
        assert "district_city" in districts

    def test_capital_prio_zones_include_industrial(self, exception_blocks):
        block = exception_blocks["automate_eca_proactive_capital"]
        zones = get_prio_zones(block)
        assert "zone_industrial" in zones
        assert "zone_research_unity" in zones


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 9: Bug regression — Factory world building research labs
# ═══════════════════════════════════════════════════════════════════════════════


class TestFactoryWorldHousing:
    """Factory world should have city districts in prio_districts for housing."""

    def test_factory_has_city_district(self, automation_blocks):
        """BUG: Factory world had no city district, so when housing went red
        it built research labs (from vanilla exceptions) instead of housing."""
        block = automation_blocks["automate_eca_factory"]
        districts = get_prio_districts(block)
        assert "district_city" in districts, \
            "Factory world must include district_city for housing"

    def test_foundry_has_city_district(self, automation_blocks):
        block = automation_blocks["automate_eca_foundry"]
        districts = get_prio_districts(block)
        assert "district_city" in districts

    def test_research_has_city_district(self, automation_blocks):
        block = automation_blocks["automate_eca_research"]
        districts = get_prio_districts(block)
        assert "district_city" in districts

    def test_industrial_has_city_district(self, automation_blocks):
        block = automation_blocks["automate_eca_industrial"]
        districts = get_prio_districts(block)
        assert "district_city" in districts

    def test_specialist_worlds_prefer_arcology_over_city(self, automation_blocks):
        """Arcology housing should appear before city district."""
        for name in ("automate_eca_foundry", "automate_eca_factory",
                     "automate_eca_research", "automate_eca_industrial"):
            block = automation_blocks[name]
            districts = get_prio_districts(block)
            arc_idx = districts.index("district_arcology_housing")
            city_idx = districts.index("district_city")
            assert arc_idx < city_idx, \
                f"{name}: arcology housing should come before city district"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 10: Structural checks — all designations covered
# ═══════════════════════════════════════════════════════════════════════════════


ALL_DESIGNATIONS = [
    "col_eca_capital", "col_eca_mining", "col_eca_generator", "col_eca_farming",
    "col_eca_foundry", "col_eca_factory", "col_eca_research", "col_eca_industrial",
]


class TestDesignationCoverage:
    """Verify all 8 designations are covered by emergency blocks."""

    @pytest.mark.parametrize("designation", ALL_DESIGNATIONS)
    def test_holo_theatre_covers_all_designations(self, exception_blocks, designation):
        planet = PlanetState(
            designation=designation,
            free_building_slots=1,
            free_amenities=-5,
            num_pops=10,
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_holo_theatre"]
        assert evaluate_available(block, planet), \
            f"Holo theatre should fire on {designation}"

    @pytest.mark.parametrize("designation", ALL_DESIGNATIONS)
    def test_precinct_covers_all_designations(self, exception_blocks, designation):
        planet = PlanetState(
            designation=designation,
            free_building_slots=1,
            num_pops=10,
            planet_stability=40,
            buildings={},
            forbidden_jobs=set(),
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_stability_precinct"]
        assert evaluate_available(block, planet)

    @pytest.mark.parametrize("designation", ALL_DESIGNATIONS)
    def test_upgrade_covers_all_designations(self, exception_blocks, designation):
        planet = PlanetState(
            designation=designation,
            free_building_slots=1,
            num_pops=10,
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_upgrade_buildings"]
        assert evaluate_available(block, planet)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 11: Deficit-reactive building
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeficitReactive:
    """Cross-designation deficit building fires on ANY ECA planet."""

    def test_alloy_deficit_builds_foundry_on_mining_world(self, exception_blocks):
        empire = healthy_empire()
        empire.monthly_income["alloys"] = 1  # deficit
        planet = PlanetState(
            designation="col_eca_mining",
            free_building_slots=1,
            num_pops=10,
            owner=empire,
        )
        block = exception_blocks["automate_eca_deficit_alloys"]
        assert evaluate_available(block, planet)

    def test_cg_deficit_builds_factory_on_generator_world(self, exception_blocks):
        empire = healthy_empire()
        empire.monthly_income["consumer_goods"] = 1
        planet = PlanetState(
            designation="col_eca_generator",
            free_building_slots=1,
            num_pops=10,
            owner=empire,
        )
        block = exception_blocks["automate_eca_deficit_consumer_goods"]
        assert evaluate_available(block, planet)

    def test_no_alloy_deficit_no_foundry(self, exception_blocks):
        """Should NOT build foundry if alloys are healthy."""
        planet = PlanetState(
            designation="col_eca_mining",
            free_building_slots=1,
            num_pops=10,
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_deficit_alloys"]
        assert not evaluate_available(block, planet)

    def test_energy_deficit_builds_generator_district(self, exception_blocks):
        empire = healthy_empire()
        empire.monthly_income["energy"] = -15  # severe deficit
        planet = PlanetState(
            designation="col_eca_mining",
            free_district_slots=3,
            num_pops=10,
            owner=empire,
        )
        block = exception_blocks["automate_eca_deficit_energy"]
        assert evaluate_available(block, planet)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 12: Building priority (would_build)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildingPriority:
    """Test which buildings pass availability for different scenarios."""

    def test_capital_builds_foundry_only_during_deficit(self, automation_blocks):
        """Capital should NOT build foundry when alloys are healthy."""
        block = automation_blocks["automate_eca_capital"]
        # Healthy empire
        planet = PlanetState(
            designation="col_eca_capital",
            num_pops=10,
            free_amenities=10,
            owner=healthy_empire(),
        )
        buildings = would_build(block, planet)
        assert "building_foundry_1" not in buildings

    def test_capital_builds_foundry_during_deficit(self, automation_blocks):
        empire = healthy_empire()
        empire.monthly_income["alloys"] = 1  # deficit
        block = automation_blocks["automate_eca_capital"]
        planet = PlanetState(
            designation="col_eca_capital",
            num_pops=10,
            free_amenities=10,
            owner=empire,
        )
        buildings = would_build(block, planet)
        assert "building_foundry_1" in buildings

    def test_mining_world_always_includes_deposit_extractors(self, automation_blocks):
        block = automation_blocks["automate_eca_mining"]
        planet = PlanetState(
            designation="col_eca_mining",
            num_pops=10,
            free_amenities=10,
            owner=healthy_empire(),
        )
        buildings = would_build(block, planet)
        assert "building_crystal_mines" in buildings
        assert "building_mote_harvesters" in buildings
        assert "building_gas_extractors" in buildings

    def test_research_world_blocks_labs_without_cg_surplus(self, automation_blocks):
        """Research labs require CG >= 10 surplus."""
        empire = healthy_empire()
        empire.monthly_income["consumer_goods"] = 5
        block = automation_blocks["automate_eca_research"]
        planet = PlanetState(
            designation="col_eca_research",
            num_pops=10,
            free_amenities=10,
            owner=empire,
        )
        buildings = would_build(block, planet)
        # The stackable research labs (7, 8, 9) should be blocked
        assert "building_engineering_facility_1" not in buildings
        assert "building_physics_lab_1" not in buildings
        assert "building_biolab_1" not in buildings


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 13: Gestalt exclusion
# ═══════════════════════════════════════════════════════════════════════════════


class TestGestaltExclusion:
    """Gestalt empires should be excluded from ECA-specific blocks."""

    def test_robot_assembly_excludes_gestalt(self, exception_blocks):
        planet = PlanetState(
            designation="col_eca_mining",
            free_building_slots=2,
            num_pops=10,
            unemployed_pops=0,
            can_assemble_robot=True,
            owner=healthy_empire(is_regular_empire=False, is_gestalt=True),
        )
        block = exception_blocks["automate_eca_robot_assembly"]
        assert not evaluate_available(block, planet)

    def test_gene_clinic_excludes_gestalt(self, exception_blocks):
        planet = PlanetState(
            designation="col_eca_mining",
            free_building_slots=2,
            num_pops=10,
            unemployed_pops=0,
            owner=healthy_empire(is_regular_empire=False, is_gestalt=True),
        )
        block = exception_blocks["automate_eca_gene_clinic"]
        assert not evaluate_available(block, planet)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 14: Edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Miscellaneous edge cases."""

    def test_no_building_slots_blocks_everything(self, exception_blocks):
        """Building blocks require free_building_slots > 0."""
        planet = PlanetState(
            designation="col_eca_mining",
            free_building_slots=0,
            num_pops=10,
            unemployed_pops=0,
            can_assemble_robot=True,
            free_amenities=-5,
            owner=healthy_empire(),
        )
        for name in ("automate_eca_robot_assembly", "automate_eca_gene_clinic",
                      "automate_eca_holo_theatre"):
            block = exception_blocks[name]
            assert not evaluate_available(block, planet), \
                f"{name} should not fire with 0 building slots"

    def test_no_district_slots_blocks_proactive(self, exception_blocks):
        """District blocks require free_district_slots > 0."""
        planet = PlanetState(
            designation="col_eca_mining",
            free_district_slots=0,
            num_pops=10,
            available_jobs={},
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_proactive_mining"]
        assert not evaluate_available(block, planet)

    def test_wrong_designation_blocks_proactive(self, exception_blocks):
        """Mining proactive should only fire on col_eca_mining."""
        planet = PlanetState(
            designation="col_eca_generator",
            free_district_slots=5,
            num_pops=10,
            available_jobs={},
            owner=healthy_empire(),
        )
        block = exception_blocks["automate_eca_proactive_mining"]
        assert not evaluate_available(block, planet)
