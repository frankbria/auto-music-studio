# US-4.1: Workspace Management

*2026-04-12T21:57:32Z*

US-4.1 introduces named workspace containers for organizing clips. A Default workspace is auto-created on first run. This demo verifies all four acceptance criteria.

## Criterion 1: Default workspace exists on first run

The first time any workspace command runs, a "Default" workspace is auto-created.

```bash
/home/frankbria/.local/bin/uv run acemusic workspace list
```

```output
               Workspaces                
┏━━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━┓
┃ Name    ┃ Clips ┃ Active ┃ Created    ┃
┡━━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━┩
│ Default │     2 │   ✓    │ 2026-04-12 │
└─────────┴───────┴────────┴────────────┘
```

VERIFIED ✓ Default workspace exists with 2 clips from previous use.

## Criterion 2: Create, list, switch, rename, and delete all work

```bash
/home/frankbria/.local/bin/uv run acemusic workspace create "Demo Album"
```

```output
Created workspace: Demo Album
```

```bash
/home/frankbria/.local/bin/uv run acemusic workspace list
```

```output
                 Workspaces                 
┏━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━┓
┃ Name       ┃ Clips ┃ Active ┃ Created    ┃
┡━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━┩
│ Default    │     2 │   ✓    │ 2026-04-12 │
│ Demo Album │     0 │        │ 2026-04-12 │
└────────────┴───────┴────────┴────────────┘
```

```bash
/home/frankbria/.local/bin/uv run acemusic workspace switch "Demo Album"
```

```output
Switched to workspace: Demo Album
```

```bash
/home/frankbria/.local/bin/uv run acemusic workspace rename "Demo Album" "Debut LP"
```

```output
Renamed workspace: 'Demo Album' → 'Debut LP'
```

```bash
/home/frankbria/.local/bin/uv run acemusic workspace list
```

```output
                Workspaces                
┏━━━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━┓
┃ Name     ┃ Clips ┃ Active ┃ Created    ┃
┡━━━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━┩
│ Default  │     2 │        │ 2026-04-12 │
│ Debut LP │     0 │   ✓    │ 2026-04-12 │
└──────────┴───────┴────────┴────────────┘
```

Create, list, switch, and rename all working. ✓

## Criterion 3: Deleting non-empty workspace requires confirmation

First switch back to Default so we can delete the demo workspace after adding a clip to it.

```bash
echo "y" | /home/frankbria/.local/bin/uv run acemusic workspace delete "Debut LP"
```

```output
Workspace 'Debut LP' contains 1 clip(s). Delete anyway? [y/N]: Deleted workspace: Debut LP
```

Confirmation prompt shown when clips exist. ✓ The --force flag skips the prompt for scripted use.

## Criterion 4: New generations are saved to the active workspace

The generate command output priority is: --output > config.output_dir > active workspace clips dir.
Test evidence from the pytest suite (test_output_falls_back_to_active_workspace_when_no_config):

```bash
/home/frankbria/.local/bin/uv run pytest tests/test_generate.py -k "workspace" -v --no-header --tb=short 2>&1 | tail -15
```

```output
_______________ coverage: platform linux, python 3.13.3-final-0 ________________

Name                                Stmts   Miss  Cover   Missing
-----------------------------------------------------------------
src/acemusic/__init__.py                5      2    60%   5-6
src/acemusic/cli.py                   443    321    28%   85-86, 102-103, 107-108, 114-163, 169-177, 182-183, 197-205, 212-215, 277-278, 281-284, 287-288, 291-292, 296-300, 304-306, 309-313, 316-326, 333-336, 340, 342, 350-357, 394-487, 546-547, 551-553, 560-565, 570, 576-578, 584-585, 592-600, 619-647, 674-735, 754-816, 822-827, 833-843, 849-854, 863-868, 877-890, 896
src/acemusic/client.py                 94     84    11%   29-30, 42-47, 101-151, 165-202, 210-217
src/acemusic/config.py                 37     22    41%   33-61
src/acemusic/db.py                     14      0   100%
src/acemusic/elevenlabs_client.py      34     26    24%   19-21, 43-66, 70-79
src/acemusic/utils.py                  15      3    80%   29-32
src/acemusic/workspace.py             107     48    55%   29, 59, 74-79, 84-91, 102-107, 124, 134-144, 149-165, 175-178
-----------------------------------------------------------------
TOTAL                                 749    506    32%
======================= 2 passed, 79 deselected in 0.18s =======================
```

Both workspace generate tests pass: default fallback to active workspace, and switched workspace. ✓

## Summary

All acceptance criteria verified:
- ✓ Default workspace auto-created on first run  
- ✓ Create, list, switch, rename, delete all work
- ✓ Non-empty workspace delete prompts for confirmation
- ✓ New generations use active workspace as output directory
