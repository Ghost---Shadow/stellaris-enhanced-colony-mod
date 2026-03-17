"""
Clausewitz script parser and condition evaluator for Stellaris mod testing.

Parses .txt mod files into a structured AST, and evaluates `available` blocks
against simulated planet/empire state to verify automation logic without
launching the game.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Union


# ─── Tokenizer ───────────────────────────────────────────────────────────────

TOKEN_PATTERN = re.compile(
    r"""
    (?P<COMMENT>\#[^\n]*)              |  # line comment
    (?P<LBRACE>\{)                     |
    (?P<RBRACE>\})                     |
    (?P<OP>[<>!=]=?|==)                |  # operators
    (?P<STRING>"[^"]*")                |  # quoted string
    (?P<ID>[a-zA-Z_@][\w.]*)          |  # identifier (allows @ prefix for variables)
    (?P<NUMID>\d+[a-zA-Z_]\w*)        |  # numeric-prefixed identifier (7_admin, 2_corp)
    (?P<NUMBER>-?\d+(?:\.\d+)?)        |  # numbers (int or float)
    (?P<YES_NO>(?:yes|no)\b)           |  # boolean literals
    (?P<WS>\s+)                           # whitespace
    """,
    re.VERBOSE,
)


@dataclass
class Token:
    kind: str
    value: str
    pos: int


def tokenize(text: str) -> list[Token]:
    """Tokenize Clausewitz script text into a list of tokens."""
    tokens: list[Token] = []
    for m in TOKEN_PATTERN.finditer(text):
        kind = m.lastgroup
        if kind in ("WS", "COMMENT"):
            continue
        value = m.group()
        if kind == "STRING":
            value = value[1:-1]  # strip quotes
        elif kind == "YES_NO":
            kind = "ID"  # treat yes/no as identifiers
        elif kind == "NUMID":
            kind = "ID"  # treat numeric-prefixed ids (7_admin) as identifiers
        tokens.append(Token(kind, value, m.start()))
    return tokens


# ─── Parser ──────────────────────────────────────────────────────────────────
#
# Clausewitz grammar (simplified):
#   file       = (statement)*
#   statement  = ID '=' value | ID '{' block '}' | ID OP value
#   value      = NUMBER | STRING | ID | '{' block '}'
#   block      = (statement)*
#
# We represent parsed data as a list of (key, operator, value) triples.
# When value is a nested block, it's a list of triples.


ParsedBlock = list[tuple[str, str, Any]]


class ParseError(Exception):
    pass


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def advance(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, kind: str) -> Token:
        t = self.advance()
        if t.kind != kind:
            raise ParseError(f"Expected {kind}, got {t.kind} ({t.value!r}) at pos {t.pos}")
        return t

    def parse_file(self) -> ParsedBlock:
        """Parse entire file into a list of (key, op, value) triples."""
        stmts = []
        while self.pos < len(self.tokens):
            t = self.peek()
            if t is None or t.kind == "RBRACE":
                break
            stmts.append(self._parse_statement())
        return stmts

    def _parse_statement(self) -> tuple[str, str, Any]:
        # Keys can be identifiers (has_designation) or numbers (1, 2, 7_admin)
        t = self.peek()
        if t is None:
            raise ParseError("Unexpected end of input while parsing statement")
        if t.kind in ("ID", "NUMBER", "STRING"):
            key_tok = self.advance()
        else:
            raise ParseError(f"Expected key (ID or NUMBER), got {t.kind} ({t.value!r}) at pos {t.pos}")
        key = key_tok.value
        nxt = self.peek()

        if nxt is None:
            return (key, "=", True)

        # key = value  or  key < value  etc.
        if nxt.kind == "OP":
            op = self.advance().value
            return (key, op, self._parse_value())

        # key { block }  (implicit = for blocks without operator)
        if nxt.kind == "LBRACE":
            self.advance()  # consume {
            block = self.parse_file()
            self.expect("RBRACE")
            return (key, "=", block)

        # Bare identifier (e.g., "emergency" followed by "=" on next token?)
        # Actually this shouldn't happen in well-formed Clausewitz, but handle gracefully
        return (key, "=", True)

    def _parse_value(self) -> Any:
        t = self.peek()
        if t is None:
            raise ParseError("Unexpected end of input while parsing value")

        if t.kind == "LBRACE":
            self.advance()
            block = self.parse_file()
            self.expect("RBRACE")
            return block

        if t.kind == "NUMBER":
            self.advance()
            return float(t.value) if "." in t.value else int(t.value)

        if t.kind in ("ID", "STRING"):
            self.advance()
            if t.value == "yes":
                return True
            if t.value == "no":
                return False
            return t.value

        raise ParseError(f"Unexpected token {t.kind} ({t.value!r}) at pos {t.pos}")


def parse_clausewitz(text: str) -> ParsedBlock:
    """Parse a Clausewitz script string into a structured block."""
    tokens = tokenize(text)
    parser = Parser(tokens)
    return parser.parse_file()


def parse_file(path: str | Path) -> ParsedBlock:
    """Parse a Clausewitz file from disk."""
    text = Path(path).read_text(encoding="utf-8-sig")  # handles BOM
    return parse_clausewitz(text)


# ─── Helpers to query parsed blocks ─────────────────────────────────────────


def find_blocks(parsed: ParsedBlock, key: str) -> list[Any]:
    """Find all values associated with a given key in a parsed block."""
    return [v for k, op, v in parsed if k == key]


def get_value(parsed: ParsedBlock, key: str, default: Any = None) -> Any:
    """Get the first value for a key, or default."""
    for k, op, v in parsed:
        if k == key:
            return v
    return default


def get_all_automation_blocks(parsed: ParsedBlock) -> dict[str, ParsedBlock]:
    """Extract all top-level automation blocks (automate_*) from a parsed file.

    Returns dict mapping block name -> parsed block content.
    """
    result = {}
    for key, op, value in parsed:
        if key.startswith("automate_") and isinstance(value, list):
            result[key] = value
    return result


# ─── State Dataclasses ──────────────────────────────────────────────────────


@dataclass
class EmpireState:
    """Simulated empire (country) state for condition evaluation."""

    is_regular_empire: bool = True
    is_gestalt: bool = False
    is_synthetic_empire: bool = False
    is_spiritualist: bool = False
    has_make_spiritualist_perk: bool = False
    country_uses_consumer_goods: bool = True

    # resource -> monthly income
    monthly_income: dict[str, float] = field(default_factory=lambda: {
        "minerals": 50, "energy": 30, "food": 20,
        "alloys": 10, "consumer_goods": 10,
        "rare_crystals": 2, "volatile_motes": 2, "exotic_gases": 2,
    })

    # resource -> stockpile amount
    stockpiles: dict[str, float] = field(default_factory=lambda: {
        "minerals": 2000, "energy": 1000, "food": 500,
        "alloys": 500, "consumer_goods": 300,
    })

    policy_flags: set[str] = field(default_factory=set)
    ascension_perks: set[str] = field(default_factory=set)

    years_passed: int = 50

    # For any_owned_planet checks — list of PlanetState objects
    owned_planets: list[Any] = field(default_factory=list)

    # Evaluated scripted triggers cache (lazy)
    _trigger_cache: dict[str, bool] = field(default_factory=dict, repr=False)


@dataclass
class PlanetState:
    """Simulated planet state for condition evaluation."""

    designation: str = "col_eca_capital"
    free_building_slots: int = 2
    free_district_slots: int = 5
    num_pops: int = 10
    free_amenities: float = 5.0
    free_housing: float = 3.0
    planet_stability: float = 60.0
    can_assemble_robot: bool = True

    # job_name -> number of OPEN (unfilled) positions
    available_jobs: dict[str, int] = field(default_factory=dict)

    # building_id -> count on planet
    buildings: dict[str, int] = field(default_factory=dict)

    # Jobs that are forbidden (e.g., by policy)
    forbidden_jobs: set[str] = field(default_factory=set)

    # Number of unemployed pops (for any_owned_pop_group checks)
    unemployed_pops: int = 0

    owner: EmpireState | None = None


# ─── Scripted Trigger Evaluator ──────────────────────────────────────────────


# Map ECA trigger names to evaluation lambdas. These mirror the definitions
# in 99_eca_scripted_triggers.txt so we can evaluate them against EmpireState.

def _make_income_check(resource: str, op: str, value: float):
    """Create a lambda that checks monthly income."""
    if op == "<":
        return lambda e: e.monthly_income.get(resource, 0) < value
    elif op == ">=":
        return lambda e: e.monthly_income.get(resource, 0) >= value
    elif op == ">":
        return lambda e: e.monthly_income.get(resource, 0) > value
    elif op == "<=":
        return lambda e: e.monthly_income.get(resource, 0) <= value
    raise ValueError(f"Unknown op {op}")


def _make_stockpile_check(resource: str, op: str, value: float):
    """Create a lambda that checks resource stockpile."""
    if op == ">=":
        return lambda e: e.stockpiles.get(resource, 0) >= value
    raise ValueError(f"Unknown op {op}")


# Scripted trigger definitions (country scope)
SCRIPTED_TRIGGERS: dict[str, Any] = {
    # Deficit triggers
    "eca_has_mineral_deficit": _make_income_check("minerals", "<", 5),
    "eca_has_severe_mineral_deficit": _make_income_check("minerals", "<", -10),
    "eca_has_energy_deficit": _make_income_check("energy", "<", 5),
    "eca_has_severe_energy_deficit": _make_income_check("energy", "<", -10),
    "eca_has_food_deficit": _make_income_check("food", "<", 3),
    "eca_has_severe_food_deficit": _make_income_check("food", "<", -5),
    "eca_has_alloy_deficit": _make_income_check("alloys", "<", 3),
    "eca_has_consumer_goods_deficit": _make_income_check("consumer_goods", "<", 3),
    "eca_has_rare_crystal_deficit": _make_income_check("rare_crystals", "<", 1),
    "eca_has_volatile_mote_deficit": _make_income_check("volatile_motes", "<", 1),
    "eca_has_exotic_gas_deficit": _make_income_check("exotic_gases", "<", 1),
    # Surplus triggers
    "eca_has_mineral_surplus": _make_income_check("minerals", ">", 50),
    "eca_has_energy_surplus": _make_income_check("energy", ">", 30),
    "eca_has_alloy_surplus": _make_income_check("alloys", ">", 15),
    # Affordability - upkeep
    "eca_can_afford_research_upkeep": _make_income_check("consumer_goods", ">=", 10),
    "eca_can_afford_foundry_upkeep": _make_income_check("minerals", ">=", 12),
    "eca_can_afford_factory_upkeep": _make_income_check("minerals", ">=", 12),
    "eca_can_afford_strategic_upkeep": _make_income_check("minerals", ">=", 20),
    "eca_can_afford_energy_upkeep": _make_income_check("energy", ">=", 4),
    "eca_can_afford_robot_assembly_upkeep": _make_income_check("alloys", ">=", 4),
    # Affordability - build cost
    "eca_can_afford_build_cost_200": _make_stockpile_check("minerals", ">=", 400),
    "eca_can_afford_build_cost_300": _make_stockpile_check("minerals", ">=", 600),
    "eca_can_afford_build_cost_400": _make_stockpile_check("minerals", ">=", 800),
    "eca_can_afford_build_cost_500": _make_stockpile_check("minerals", ">=", 1000),
    "eca_can_afford_build_cost_600": _make_stockpile_check("minerals", ">=", 1200),
    # Phase triggers
    "eca_is_early_game": lambda e: e.years_passed < 30,
    "eca_is_mid_game": lambda e: 30 <= e.years_passed < 75,
    "eca_is_late_game": lambda e: e.years_passed >= 75,
}


# ─── Condition Evaluator ────────────────────────────────────────────────────


class EvalError(Exception):
    """Raised when evaluation encounters an unknown condition."""
    pass


def evaluate_condition(cond: tuple[str, str, Any], planet: PlanetState) -> bool:
    """Evaluate a single (key, op, value) condition triple against planet state.

    Returns True if the condition is met, False otherwise.
    Raises EvalError for unknown conditions (so tests can catch gaps).
    """
    key, op, value = cond
    empire = planet.owner

    # ── Logic operators ──
    if key == "OR":
        assert isinstance(value, list)
        return any(evaluate_condition(c, planet) for c in value)

    if key == "AND":
        assert isinstance(value, list)
        return all(evaluate_condition(c, planet) for c in value)

    if key == "NOT":
        assert isinstance(value, list)
        # NOT block contains conditions that must ALL be false
        return not all(evaluate_condition(c, planet) for c in value)

    # ── Planet-scope conditions ──
    if key == "has_designation":
        return planet.designation == value

    if key == "free_building_slots":
        return _compare(planet.free_building_slots, op, value)

    if key == "free_district_slots":
        return _compare(planet.free_district_slots, op, value)

    if key == "num_pops":
        return _compare(planet.num_pops, op, value)

    if key == "free_amenities":
        return _compare(planet.free_amenities, op, value)

    if key == "free_housing":
        return _compare(planet.free_housing, op, value)

    if key == "planet_stability":
        return _compare(planet.planet_stability, op, value)

    if key == "can_assemble_robot":
        return planet.can_assemble_robot == (value is True or value == "yes")

    if key == "has_available_jobs":
        job = value
        return planet.available_jobs.get(job, 0) > 0

    if key == "has_building":
        return planet.buildings.get(value, 0) > 0

    if key == "has_forbidden_jobs":
        return value in planet.forbidden_jobs

    if key == "num_buildings":
        # value is a block like [("type", "=", "building_x"), ("value", "<", 1)]
        assert isinstance(value, list)
        btype = get_value(value, "type")
        threshold = get_value(value, "value")
        bop = "="
        for k2, o2, v2 in value:
            if k2 == "value":
                bop = o2
                threshold = v2
        count = planet.buildings.get(btype, 0)
        return _compare(count, bop, threshold)

    if key == "any_owned_pop_group":
        # value is a block, typically [("is_unemployed", "=", True)]
        assert isinstance(value, list)
        is_unemployed_check = get_value(value, "is_unemployed")
        if is_unemployed_check is True:
            return planet.unemployed_pops > 0
        return planet.unemployed_pops == 0

    # ── Owner scope ──
    if key == "exists":
        if value == "owner":
            return empire is not None
        return True  # conservative

    if key == "owner":
        # value is a block of conditions in country scope
        assert isinstance(value, list)
        if empire is None:
            return False
        return all(_evaluate_country_condition(c, empire, planet) for c in value)

    # ── Catch-all for unknown conditions ──
    raise EvalError(f"Unknown planet condition: {key} {op} {value!r}")


def _evaluate_country_condition(
    cond: tuple[str, str, Any], empire: EmpireState, planet: PlanetState
) -> bool:
    """Evaluate a condition in country (owner) scope."""
    key, op, value = cond

    # Logic operators
    if key == "OR":
        assert isinstance(value, list)
        return any(_evaluate_country_condition(c, empire, planet) for c in value)
    if key == "AND":
        assert isinstance(value, list)
        return all(_evaluate_country_condition(c, empire, planet) for c in value)
    if key == "NOT":
        assert isinstance(value, list)
        return not all(_evaluate_country_condition(c, empire, planet) for c in value)

    # Empire boolean flags
    if key == "is_regular_empire":
        return empire.is_regular_empire == (value is True)
    if key == "is_gestalt":
        return empire.is_gestalt == (value is True)
    if key == "is_synthetic_empire":
        return empire.is_synthetic_empire == (value is True)
    if key == "is_spiritualist":
        return empire.is_spiritualist == (value is True)
    if key == "has_make_spiritualist_perk":
        return empire.has_make_spiritualist_perk == (value is True)
    if key == "country_uses_consumer_goods":
        return empire.country_uses_consumer_goods == (value is True)

    # Policy flags
    if key == "has_policy_flag":
        flag_present = value in empire.policy_flags
        return flag_present  # default op is =, value is the flag name

    # Ascension perks
    if key == "has_ascension_perk":
        return value in empire.ascension_perks

    # Resource checks
    if key == "has_monthly_income":
        assert isinstance(value, list)
        resource = get_value(value, "resource")
        for k2, o2, v2 in value:
            if k2 == "value":
                actual = empire.monthly_income.get(resource, 0)
                return _compare(actual, o2, v2)
        return True

    if key == "has_resource":
        assert isinstance(value, list)
        rtype = get_value(value, "type")
        for k2, o2, v2 in value:
            if k2 == "amount":
                actual = empire.stockpiles.get(rtype, 0)
                return _compare(actual, o2, v2)
        return True

    # any_owned_planet (for deficit prefer-dedicated-world checks)
    if key == "any_owned_planet":
        assert isinstance(value, list)
        for p in empire.owned_planets:
            if all(evaluate_condition(c, p) for c in value):
                return True
        return False

    # Years passed
    if key == "years_passed":
        return _compare(empire.years_passed, op, value)

    # ECA scripted triggers
    if key in SCRIPTED_TRIGGERS:
        result = SCRIPTED_TRIGGERS[key](empire)
        expected = value if isinstance(value, bool) else (value == "yes")
        return result == expected

    raise EvalError(f"Unknown country condition: {key} {op} {value!r}")


def _compare(actual: float, op: str, expected: float) -> bool:
    """Compare two numeric values with the given operator."""
    if op in ("=", "=="):
        return actual == expected
    if op == "<":
        return actual < expected
    if op == ">":
        return actual > expected
    if op == "<=":
        return actual <= expected
    if op == ">=":
        return actual >= expected
    if op == "!=":
        return actual != expected
    raise ValueError(f"Unknown operator: {op}")


# ─── High-level Evaluation API ──────────────────────────────────────────────


def evaluate_available(block: ParsedBlock, planet: PlanetState) -> bool:
    """Evaluate the `available` block of an automation entry.

    Args:
        block: The parsed content of an automation block (e.g., automate_eca_capital).
        planet: The simulated planet state.

    Returns:
        True if all conditions in the `available` block are satisfied.
    """
    available = find_blocks(block, "available")
    if not available:
        return True  # no conditions = always available
    # available[0] is the first (and typically only) available block
    conditions = available[0]
    assert isinstance(conditions, list)
    return all(evaluate_condition(c, planet) for c in conditions)


def would_build(block: ParsedBlock, planet: PlanetState) -> list[str]:
    """Return list of building IDs that an automation block would attempt to build.

    Only returns buildings whose individual `available` sub-blocks (if any) pass.
    Does NOT check the top-level `available` — call evaluate_available() first.
    """
    buildings_block = find_blocks(block, "buildings")
    if not buildings_block:
        return []
    buildings = buildings_block[0]
    assert isinstance(buildings, list)

    result = []
    for entry_key, entry_op, entry_value in buildings:
        if not isinstance(entry_value, list):
            continue
        building_id = get_value(entry_value, "building")
        if building_id is None:
            continue
        # Check entry-level available block
        entry_available = find_blocks(entry_value, "available")
        if entry_available:
            conditions = entry_available[0]
            if not all(evaluate_condition(c, planet) for c in conditions):
                continue
        result.append(building_id)
    return result


def get_prio_districts(block: ParsedBlock) -> list[str]:
    """Extract prio_districts list from an automation block."""
    prio = find_blocks(block, "prio_districts")
    if not prio:
        return []
    return [k for k, _, _ in prio[0]]


def get_prio_zones(block: ParsedBlock) -> list[str]:
    """Extract prio_zones list from an automation block."""
    prio = find_blocks(block, "prio_zones")
    if not prio:
        return []
    return [k for k, _, _ in prio[0]]
