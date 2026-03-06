# Enhanced Colony Automation AI

A Stellaris mod that adds 8 new colony designations with smarter automation logic. Designed for **regular empires** (non-gestalt) and runs alongside vanilla designations for A/B comparison.

**Supported version:** Stellaris 4.2.*

## What This Mod Does

Vanilla colony automation has several weaknesses: sparse building priority lists, no awareness of empire-wide resource deficits, reactive-only infrastructure building, and slow designation re-evaluation. This mod addresses all of these with new "Enhanced" colony designations.

### Key Features

- **8 new colony designations** (Enhanced Capital, Mining, Generator, Farming, Foundry, Factory, Research, Industrial) that coexist with vanilla
- **Deficit-reactive building** — builds production buildings even without free pops when the empire is running a deficit (e.g., a mining world builds a factory if the empire desperately needs consumer goods)
- **Proactive district/zone building** — builds the next district or zone when all pops are employed, keeping ~1 job opening ready for the next pop
- **NPV-optimized build order** — building priorities ordered by net present value so the most impactful investments happen first
- **2x affordability buffer** — only builds expensive buildings (foundries, factories, refineries, robot assemblies) if the empire can afford twice the monthly upkeep. This gives the human player breathing room — automated planets won't eat into your resource surplus right before you click that "build" button yourself
- **Emergency pop growth** — builds gene clinics and robot assembly plants proactively, bypassing the normal "must have free pops" check
- **Smarter job checks** — uses correct Stellaris 4.x job IDs (`foundry`, `physicist`/`biologist`/`engineer`, etc.)

## File Structure

```
EnhancedColonyAI/
├── common/
│   ├── colony_automation/
│   │   └── 01_eca_automation.txt          # Core automation rules for all 8 designations
│   ├── colony_automation_exceptions/
│   │   └── 01_eca_exceptions.txt          # Emergency & proactive building rules
│   ├── colony_types/
│   │   └── 01_eca_colony_types.txt        # Colony designation definitions & weights
│   └── scripted_triggers/
│       └── 99_eca_scripted_triggers.txt   # Reusable deficit/surplus/affordability triggers
├── localisation/
│   └── english/
│       └── enhanced_colony_ai_l_english.yml
├── tools/
│   └── npv_calculator.py                  # NPV calculator & automation file generator
└── descriptor.mod
```

## How It Works

All files use the `01_` or `99_` prefix so they load additively alongside vanilla (`00_`) files. Nothing is replaced — vanilla designations remain available.

### Colony Designations

Each Enhanced designation (prefixed `col_eca_`) provides the same resource bonuses as its vanilla counterpart but uses the improved automation logic:

| Designation | Focus | Key Automation Behavior |
|---|---|---|
| Enhanced Capital | Balanced | Builds foundries, factories, admin offices, research labs |
| Enhanced Mining | Minerals | Deposit extractors first, deficit-conditional off-designation buildings |
| Enhanced Generator | Energy | Same pattern as mining, energy-focused |
| Enhanced Farming | Food | Same pattern, food-focused |
| Enhanced Foundry | Alloys | Zone-based specialist building, no city district spam |
| Enhanced Factory | Consumer Goods | Zone-based, affordability-gated |
| Enhanced Research | Research | Zone-based, checks all 3 researcher jobs (physicist/biologist/engineer) |
| Enhanced Industrial | Alloys + CG | Combined foundry/factory logic |

### Emergency Exceptions

These fire with `emergency = yes`, bypassing the normal free-pops requirement:

- **Robot assembly** — builds `building_robot_assembly_plant` if empire has 4+ alloy surplus (2x the 2 alloy/month roboticist upkeep)
- **Gene clinic** — builds on any ECA planet for organic empires
- **Proactive districts/zones** — builds when all pops are employed AND no relevant jobs are open, OR when empire has a deficit
- **Cross-designation deficit building** — any ECA planet builds alloy foundries, consumer goods factories, or resource districts when the empire has a severe deficit

### Scripted Triggers

Reusable triggers in country/planet scope:

- `eca_has_*_deficit` — checks if monthly income is dangerously low
- `eca_has_severe_*_deficit` — checks for actively negative income
- `eca_can_afford_*_upkeep` — 2x affordability buffer checks (requires surplus ≥ 2× the building's monthly upkeep, so automation never steals resources the player is about to spend)
- `eca_planet_needs_amenities` / `eca_planet_needs_housing` — planet-level checks

## NPV Calculator

`tools/npv_calculator.py` computes net present value for all buildings and districts, and can regenerate the automation file:

```bash
# Print NPV rankings
python tools/npv_calculator.py

# Regenerate 01_eca_automation.txt from computed priorities
python tools/npv_calculator.py --generate
```

When Stellaris updates, adjust the cost/upkeep/production numbers in the script and re-run to get updated build priorities.

## Installation

1. Clone or download to your Stellaris mod directory:
   ```
   Documents/Paradox Interactive/Stellaris/mod/EnhancedColonyAI/
   ```
2. Ensure `EnhancedColonyAI.mod` is in the parent `mod/` directory
3. Enable the mod in the Stellaris launcher
4. In-game, manually assign "Enhanced ..." designations to your colonies

## Compatibility

- **Additive design** — does not replace any vanilla files, so it should be compatible with most mods
- **Regular empires only** — gestalt empires (hive minds, machine intelligences) are excluded from all ECA logic
- **No DLC required** — works with base game, gracefully skips buildings the player hasn't researched
