# Path of Exile 2 Build Optimizer MCP

[![PyPI version](https://badge.fury.io/py/poe2-mcp.svg)](https://pypi.org/project/poe2-mcp/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **Community Project Disclaimer**
>
> This is an independent, fan-made community project built out of love for Path of Exile 2. It is **not affiliated with, endorsed by, or officially connected to Grinding Gear Games** in any way. Path of Exile is a trademark of Grinding Gear Games. All game data and assets remain the property of their respective owners.

A Model Context Protocol (MCP) server for Path of Exile 2 character analysis and optimization. Provides 38 MCP tools for AI-powered build analysis, passive tree analysis, item mod validation, support gem validation, and Path of Building integration (including a live bridge to a running PoB instance).

## What is This?

This is an **MCP server** - a backend service that gives AI assistants (like Claude, ChatGPT, Cursor, etc.) the ability to analyze your Path of Exile 2 characters and provide optimization recommendations.

**What it does:**
- Fetches your character data from poe.ninja
- Analyzes defensive stats, skills, gear, and passive tree
- Validates support gem combinations (prevents invalid recommendations)
- Inspects spell and support gem data
- Imports/exports Path of Building codes
- Compares your build to top ladder players
- Explains PoE2 game mechanics

**What you need:**
- An AI assistant that supports MCP (Claude Desktop, ChatGPT Desktop, Cursor, Windsurf, etc.)
- Python 3.9+ installed
- Your PoE2 character on poe.ninja (public profile)

## Quick Start

### 1. Install

**Option A: PyPI (Recommended)**
```bash
pip install poe2-mcp
```

**Option B: From Source**
```bash
git clone https://github.com/HivemindOverlord/poe2-mcp.git
cd poe2-mcp
pip install -e .
```

### 2. Connect to Your AI Assistant

Choose your platform below:

---

## Claude Desktop Integration

### Option A: Manual Configuration (Recommended for Development)

Edit your Claude Desktop config file:
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

The right config depends on how you installed. Pick one.

#### A1. If you ran `pip install poe2-mcp` (Recommended)

Use the `poe2-mcp` console script. It's on your PATH after `pip install` and works on every platform — no absolute path needed:

```json
{
  "mcpServers": {
    "poe2-optimizer": {
      "command": "poe2-mcp",
      "env": {}
    }
  }
}
```

If Claude Desktop reports it can't find `poe2-mcp`, your `pip` install directory isn't on Claude Desktop's PATH. Either run `which poe2-mcp` (`where poe2-mcp` on Windows) and use the absolute path, or fall back to `python -m`:

```json
{
  "mcpServers": {
    "poe2-optimizer": {
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "env": {}
    }
  }
}
```

#### A2. If you cloned + `pip install -e .` from source

Point at `launch.py` directly. It does some Windows-specific UTF-8 setup that the bare console script skips:

**Windows:**
```json
{
  "mcpServers": {
    "poe2-optimizer": {
      "command": "python",
      "args": ["C:\\Users\\YourName\\poe2-mcp\\launch.py"],
      "env": {}
    }
  }
}
```

**macOS/Linux:**
```json
{
  "mcpServers": {
    "poe2-optimizer": {
      "command": "python3",
      "args": ["/Users/YourName/poe2-mcp/launch.py"],
      "env": {}
    }
  }
}
```

Restart Claude Desktop after editing the config. The server will appear in your MCP tools.

### Option B: Download .mcpb Bundle (One-Click Install)

Pre-built MCP bundles are available for one-click installation in Claude Desktop:

1. Download `poe2-mcp-1.0.0.mcpb` from the [GitHub Releases](https://github.com/HivemindOverlord/poe2-mcp/releases/latest)
2. In Claude Desktop: Settings > Extensions > Install Extension
3. Select the downloaded `.mcpb` file

**Note:** The bundle is ~109MB as it includes all game data files. Python 3.9+ must be installed on your system.

> **Recommendation:** For development or if you want automatic updates, use Option A (manual configuration) with `pip install poe2-mcp`.

---

## Other AI Platforms

MCP is an open standard supported by multiple AI platforms:

### OpenAI ChatGPT Desktop
ChatGPT desktop app supports MCP servers. Configuration varies by version - check OpenAI's documentation for current setup instructions.

### Cursor AI
Cursor supports MCP via SSE protocol. Add to your Cursor settings:
```json
{
  "mcp": {
    "servers": {
      "poe2-optimizer": {
        "command": "python",
        "args": ["/path/to/poe2-mcp/launch.py"]
      }
    }
  }
}
```

### Windsurf
Windsurf has a built-in MCP Plugin Store. You can either:
- Search for "poe2" in the plugin store (if published)
- Manually add the server path in settings

### Claude Code (CLI)
```bash
# In your project directory
claude mcp add poe2-optimizer python /path/to/poe2-mcp/launch.py
```

### Other Compatible Clients
- Zed Editor
- Replit
- Codeium
- Sourcegraph
- Microsoft Semantic Kernel
- Salesforce Agentforce

Check each platform's documentation for MCP server configuration.

---

## Available Tools (38 Registered)

Once connected, you can ask your AI assistant to use these tools. The
authoritative list is `_register_tools()` in `src/mcp_server.py` — verify
the live count with:

```bash
python -c "import re; print(len(re.findall(r'types\.Tool\(\s*name=', open('src/mcp_server.py').read())))"
```

### Character Analysis
| Tool | Description |
|------|-------------|
| `analyze_character` | Full character analysis (defenses, skills, gear, passives); exposes raw `passive_node_ids` |
| `import_poe_ninja_url` | Import character from a poe.ninja profile URL (league-segment aware) |
| `compare_to_top_players` | Compare your build to ladder leaders (protobuf builds API) |
| `analyze_passive_tree` | Analyze allocated passive nodes with pathfinding |
| `calculate_character_dps` | Server-side spell **or weapon-attack** DPS (pass `weapon_damage` for bow/melee skills like Tornado Shot/Ice Shot/Snipe), including the optional DoT layer (ignite/poison/bleed + skill DoT) |
| `get_live_game_state` | Read the running PoE2 client's Client.txt (character, area, deaths) — local, no network |
| `get_game_config` | Read local game config INI (gateway, input mode, renderer) |

### Validation & Inspection
| Tool | Description |
|------|-------------|
| `validate_support_combination` | Check if support gems work together (hard + semantic conflicts) |
| `validate_build_constraints` | Validate build against game rules (flat/nested/legacy resistance schemas, null-tolerant) |
| `reconcile_defensive_stats` | Diff local EHP/defense calcs against poe.ninja's computed stats |
| `inspect_support_gem` | View complete support gem data (incl. spirit reservation) |
| `inspect_spell_gem` | View complete spell gem data (per-level costs/reservation) |
| `list_all_supports` | List all available support gems |
| `list_all_spells` | List all available spell gems |

### Passive Tree Data
| Tool | Description |
|------|-------------|
| `list_all_keystones` | List all keystones with full stats |
| `inspect_keystone` | Get complete keystone details by name |
| `list_all_notables` | List all notable passives with stats |
| `inspect_passive_node` | Get details for any passive node |
| `check_tree_freshness` | Report passive-tree data revision vs poe.ninja |

### Base Item Data
| Tool | Description |
|------|-------------|
| `list_all_base_items` | List all base item types |
| `inspect_base_item` | Get details for a specific base item |

### Item Mod Data
| Tool | Description |
|------|-------------|
| `inspect_mod` | Get complete details for a specific mod by ID |
| `list_all_mods` | List mods with filtering by type (PREFIX/SUFFIX/IMPLICIT) |
| `search_mods_by_stat` | Search for mods by keyword (e.g., "fire", "life") |
| `get_mod_tiers` | Show all tier variations of a mod family |
| `validate_item_mods` | Check if mods can legally exist together on an item |
| `get_available_mods` | List all mods available for a generation type |

### Knowledge & Discovery
| Tool | Description |
|------|-------------|
| `explain_mechanic` | Explain PoE2 mechanics / stat ids; tiered exact → substring → BM25 lexical; `cluster: true` dumps a mechanic's full stat-id + source web |
| `find_stat_sources` | Reverse lookup: which skills / passives / ascendancy nodes / mods grant a stat |
| `get_formula` | Get calculation formulas |

### Path of Building (file-based)
| Tool | Description |
|------|-------------|
| `import_pob` | Import a PoB build — from `pob_file_path`, raw `pob_xml`, or inline `pob_code` |
| `export_pob` | Export build to PoB format |
| `get_pob_code` | Get a character's PoB export via the poe.ninja profile API |

### Trade & Items
| Tool | Description |
|------|-------------|
| `search_items` | Search local item database |
| `search_trade_items` | Search official trade site (requires auth) |
| `setup_trade_auth` | Set up trade site authentication |

### Utility
| Tool | Description |
|------|-------------|
| `health_check` | Check server status |
| `clear_cache` | Clear cached data |

> **Live Path of Building bridge:** `src/pob/client.py` + the `pob_addon/`
> Lua addon implement a TCP bridge (127.0.0.1:49085) to a running PoB
> instance. The bridge client exists but its `pob_*` operations are **not
> currently registered as MCP tools** — they are used internally / via the
> integration test suite. They are not in the 38 above.
>
> **Not registered:** DPS/EHP standalone calculators, optimizers, and the
> live `pob_*` bridge ops have handlers/clients but no tool registration yet.

---

## Example Usage

Once configured, just talk to your AI naturally:

> "Analyze my character TomawarTheFourth from account Tomawar"

> "Import this poe.ninja URL: https://poe.ninja/poe2/builds/char/..."

> "Can I use Faster Projectiles and Slower Projectiles together?" (uses `validate_support_combination`)

> "Show me all support gems that work with projectiles" (uses `list_all_supports`)

> "What keystones are available for life builds?" (uses `list_all_keystones`)

> "Tell me about Chaos Inoculation" (uses `inspect_keystone`)

> "Compare my build to top Witchhunter players"

> "Explain how armor works in PoE2"

> "What prefixes can roll on items?" (uses `get_available_mods`)

> "Show me all tiers of the Strength mod" (uses `get_mod_tiers`)

> "Can Strength1 and Strength2 exist on the same item?" (uses `validate_item_mods`)

> "Search for fire resistance mods" (uses `search_mods_by_stat`)

The AI will use the appropriate tools automatically.

---

## Trade API Authentication (Optional)

For `search_trade_items` to work, you need to authenticate with pathofexile.com:

```bash
pip install playwright
playwright install chromium
python scripts/setup_trade_auth.py
```

This opens a browser for you to log in, then saves your session cookie.

---

## Local Game Database

The server includes a local database with:
- 4,975+ passive tree nodes
- 335+ ascendancy nodes (99% coverage)
- 14,269 item modifiers (2,252 prefixes, 2,037 suffixes, 8,930 implicits)
- Complete skill gem data from Path of Building
- Support gem effects and interactions
- Base items and unique items

Data is loaded from `data/` directory on startup.

### Centralized Game-Data Distribution (new in 1.0.2)

You no longer need to extract `.datc64` files from your own PoE2 install. The MCP automatically downloads the maintained game-data bundle from this repo's GitHub Releases on first run and after each patch (resolves [#53](https://github.com/HivemindOverlord/poe2-mcp/issues/53)).

**How it works:**
1. `launch.py` calls `src/data/data_distributor.ensure_data_current()` during startup
2. It compares `data/version.json` (local) against the latest release tagged `data-v*`
3. If newer data is available, it downloads `poe2-data.zip` and unzips into `data/`
4. The MCP starts with current data

**Opt out** (run your own local extraction instead):
```bash
export POE2_MCP_NO_DATA_FETCH=1   # macOS/Linux
$env:POE2_MCP_NO_DATA_FETCH=1     # PowerShell
```
Then extract via `scripts/extract_poe2_data.py` against your own licensed PoE2 install.

**Manual refresh:**
```bash
python -m src.data.data_distributor
```

**Data policy:** The bundle is extracted exclusively from the maintainer's licensed PoE2 install via the in-repo extraction scripts. No third-party wiki / scraped data is bundled. See `CLAUDE.md` "Data Source Policy" for details.

**Data currency & drift protection:** The shipped datasets are extracted
from the full Patch 0.5 table set (1,019 canonical `.datc64` balance tables
via `scripts/extract_balance_tables_v1.py`), versioned in
`data/game/version.json` (`data-v0.5.0-r12`). `data/game/schema_fingerprints.json`
records every table's row-count/row-size/hash; re-extraction diffs against it
so a future patch that adds, moves, or resizes columns fails loudly instead
of serving silently-wrong data. See `docs/GAME_DATA_RESEARCH.md` for the
reverse-engineered file format and extraction methodology.

---

## Architecture

```
poe2-mcp/
├── launch.py              # Entry point
├── src/
│   ├── mcp_server.py      # Main MCP server (38 tools registered)
│   ├── api/               # External API clients
│   │   ├── poe_ninja_api.py
│   │   ├── character_fetcher.py
│   │   └── rate_limiter.py
│   ├── analyzer/          # Analysis components
│   │   ├── character_analyzer.py
│   │   └── weakness_detector.py
│   ├── calculator/        # Numeric calculations
│   │   ├── ehp_calculator.py
│   │   ├── spirit_calculator.py
│   │   └── stun_calculator.py
│   ├── data/              # Data providers
│   │   ├── mod_data_provider.py
│   │   └── fresh_data_provider.py
│   ├── optimizer/         # Optimization engines
│   │   ├── gear_optimizer.py
│   │   └── gem_synergy_calculator.py
│   ├── parsers/           # Data parsers
│   │   ├── passive_tree_resolver.py
│   │   └── specifications/  # Datc64 format specifications
│   ├── knowledge/         # Game mechanics knowledge base
│   │   └── poe2_mechanics.py
│   └── database/          # SQLite database
│       ├── models.py
│       └── manager.py
├── data/                  # Game data files
│   ├── psg_passive_nodes.json
│   ├── poe2_support_gems_database.json
│   └── poe2_mods_extracted.json
└── tests/                 # Test suite
```

---

## Development

### Running Tests
```bash
pytest tests/ -v
```

### Running the Server Directly
```bash
# If installed via pip
poe2-mcp

# From source
python launch.py
```

### Key Files
- `src/mcp_server.py` - MCP server with 38 registered tools
- `src/data/mod_data_provider.py` - Item mod data access layer
- `src/calculator/ehp_calculator.py` - EHP calculations
- `src/optimizer/gem_synergy_calculator.py` - Support gem logic
- `data/psg_passive_nodes.json` - Passive tree database
- `data/poe2_mods_extracted.json` - Item modifier database (14,269 mods)

---

## Troubleshooting

### "Server not found" in Claude Desktop
- Check the path in config is absolute (not relative)
- Ensure Python is in your PATH
- Try running `python launch.py` manually to see errors

### "No character found"
- Your character must be on poe.ninja (public ladder)
- Character name is case-sensitive
- Try the full poe.ninja URL with `import_poe_ninja_url`

### Tools return empty results
- Database may need initialization: `python launch.py` handles this
- Check `data/` directory exists with JSON files

---

## Credits

Data sources:
- [poe.ninja](https://poe.ninja) - Character data and builds
- [Path of Building (PoE2)](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2) - Skill data
- [Path of Grinding](https://pathofgrinding.com) - Passive tree data

MCP Protocol:
- [Model Context Protocol](https://modelcontextprotocol.io)
- [mcpb Bundle Format](https://github.com/modelcontextprotocol/mcpb)

---

## License

MIT License - See [LICENSE](LICENSE) for details.

This is a community project. Not affiliated with Grinding Gear Games.

---

**[Report Issues](https://github.com/HivemindOverlord/poe2-mcp/issues)**
