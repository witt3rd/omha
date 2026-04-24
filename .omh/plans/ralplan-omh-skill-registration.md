# Plan: Fix OMH Plugin Skill Registration

**Status:** PARENT-SYNTHESIZED from 2-round consensus debate (Planner + Architect + Critic)
**Rounds:** 2 (no full APPROVE in R2, but both reviewers approved direction; remaining items are documentation/clarity)
**R1 verdicts:** Planner proposes, Architect REQUEST_CHANGES, Critic REQUEST_CHANGES
**R2 verdicts:** Architect REQUEST_CHANGES (minor), Critic REQUEST_CHANGES (minor)
**Effective consensus:** Architecture is settled; remaining items incorporated below

---

## Summary

The OMH plugin currently calls `_install_skills()` in `register()`, which uses
`shutil.copytree()` to copy skill directories from the plugin source tree into
`~/.hermes/skills/`. This is wrong: it leaks plugin-private files outside the
plugin context, silently skips updates on subsequent loads (the skip-if-exists
guard), and leaves orphaned files if the plugin is uninstalled.

The correct fix is a two-part operation:

1. **Remove `_install_skills()`** entirely from `register()`. The plugin should
   not touch the filesystem outside its own directory at load time.

2. **Add `skills.external_dirs`** to `~/.hermes/config.yaml` pointing at the
   plugin's `skills/` directory. Hermes's `prompt_builder.py` scans external
   dirs for SKILL.md files and includes them in the system prompt's
   `<available_skills>` index. This makes the plugin directory the canonical
   source of truth for skill discovery.

**Important caveat (NC-2):** The `skills.external_dirs` entry is currently
inert for the system prompt as long as the local copies in `~/.hermes/skills/omh-*/`
exist. `prompt_builder.py` builds a `seen_skill_names` set from the local
`~/.hermes/skills/` directory first (lines 748-751) and skips any external skill
whose `frontmatter_name` is already in that set (line 764). Since all five omh
skills exist locally, external_dirs contributes nothing to the prompt today.

The external_dirs entry is added now as a **future-proofing measure**: it will
be the correct discovery mechanism after local copies are eventually cleaned up
(deferred — see Dropped section). On a fresh machine with no local copies,
external_dirs works correctly from day one.

---

## Tasks

### Task 1 -- Add `skills.external_dirs` to `~/.hermes/config.yaml`
**Complexity:** Small
**Dependencies:** None

Edit `~/.hermes/config.yaml`. The file already has a `skills.external_dirs:` key
at line 225 with a null value. Populate it:

```yaml
skills:
  external_dirs:
    - ~/Code/oh-my-hermes/plugins/omh/skills
```

Use `~` notation (tilde-relative), NOT an expanded absolute path.
`get_external_skills_dirs()` in hermes-agent expands `~` at read time.
The path is a convention (repo at `~/Code/oh-my-hermes`); document in PR that
users on other machines must adjust this path.

**Category structure note (from R2 Architect C1):** When `external_dirs` points at
`plugins/omh/skills/`, the category for each skill is derived from its immediate
parent directory name (e.g. `omh-ralplan/SKILL.md` -> category `omh-ralplan`).
Each of the 5 skills will appear under its own single-skill section header in
the system prompt. The skills already use `category: omh` in their SKILL.md
frontmatter, but `_build_snapshot_entry()` derives category from directory
structure, not frontmatter. **This is acceptable** -- the skill names are
self-describing (`omh-ralplan`, `omh-ralph`, etc.) and the redundancy with the
category name is tolerable. No restructuring needed.

Verification (quick sanity check -- not a gate):
- Clear the disk snapshot: `rm ~/.hermes/.skills_prompt_snapshot.json` (or
  the equivalent file -- find with `grep _SNAPSHOT_FILENAME prompt_builder.py`)
- Restart hermes and inspect the skills listing to confirm omh-* appear
- Note: local copies currently shadow external_dirs (NC-2), so this check
  is mainly verifying no YAML parse errors and no immediate crash

**Acceptance criteria:**
- `~/.hermes/config.yaml` parses cleanly with no YAML syntax errors
- Verify parse: `python3 -c "import yaml, pathlib; cfg=yaml.safe_load(pathlib.Path('~/.hermes/config.yaml').expanduser().read_text()); print(cfg['skills']['external_dirs'])"`
- The path prints correctly

---

### Task 2 -- Clear skills snapshot cache and verify external_dirs active
**Complexity:** Small (operational)
**Dependencies:** Task 1

The disk snapshot (`.skills_prompt_snapshot.json` or similar) is validated against
the local `~/.hermes/skills/` manifest only. Adding `external_dirs` to config.yaml
does NOT auto-invalidate the disk snapshot.

**Cache mechanics (from R2 Architect C2):**
- Layer 1 (in-process LRU at `_SKILLS_PROMPT_CACHE`): IS auto-invalidated because
  the cache key includes `tuple(str(d) for d in external_dirs)`. A config change
  produces a cache miss on the next call in the SAME process.
- Layer 2 (disk snapshot): NOT auto-invalidated. Snapshot is keyed on local
  skills_dir manifest only. A config change mid-session + snapshot hit = external
  skills ignored until restart or snapshot delete.

Steps:
1. Find snapshot file: `grep -r "_SNAPSHOT" ~/.hermes/hermes-agent/agent/prompt_builder.py | head -5`
2. Delete it: `rm ~/.hermes/.skills_prompt_snapshot.json` (adjust filename from step 1)
3. **Restart any running Hermes process.** The in-process cache is only cleared on
   process start.
4. In a fresh session, verify omh-* skills appear in `/skills` listing or system prompt.

**Acceptance criteria:**
- Snapshot file absent (or freshly rebuilt after restart)
- Fresh hermes session shows omh-* skills in the skills index
- Note: even after this, if local `~/.hermes/skills/omh-*/` copies exist they shadow
  external_dirs in the system prompt (NC-2) -- this is expected and acceptable for now

---

### Task 3 -- Remove `_install_skills()` from `register()` in `__init__.py`
**Complexity:** Small
**Dependencies:** Tasks 1+2 confirmed (want external_dirs working before removing the old mechanism)

Edit `plugins/omh/__init__.py`:
- Remove `_install_skills()` call on line 56 of `register()`
- Delete the entire `_install_skills()` function (lines 19-51)
- Remove `import shutil` (line 11) -- only used by `_install_skills()`
- Remove `from pathlib import Path` (line 12) -- verify it is not used elsewhere in
  the file before removing (grep for `Path(` in the file)

After this change `register()` contains only tool and hook registrations. No
filesystem operations at load time.

**Important:** Do NOT delete `~/.hermes/skills/omh-*/` directories. Those local copies
continue to serve `skill_view()` bare-name resolution. The deferred cleanup requires
a hermes-agent change (extending `skill_view()` to search external_dirs for bare names).
See Deferred section.

Note from R2 Architect C3: `skill_view()` actually does search `get_all_skills_dirs()`
which includes external_dirs. So local copies are not strictly required for bare-name
resolution -- but keeping them is a safe conservative choice while the behavior
is unverified.

**Acceptance criteria:**
- `plugins/omh/__init__.py` contains no reference to `shutil`, `_install_skills`, or
  `shutil.copytree`
- `python -c "from plugins.omh import register"` imports cleanly with no errors
- `register()` function body contains only `ctx.register_tool()` and `ctx.register_hook()` calls
- Local `~/.hermes/skills/omh-*/` directories are untouched

---

### Task 4 -- Clean up `plugin.yaml`
**Complexity:** Small
**Dependencies:** None (independent)

Edit `plugins/omh/plugin.yaml`:

1. **Remove `entry_point: plugin`** (line 4). Confirmed dead code by Architect:
   `_parse_manifest()` never reads this field; `_load_directory_module()` loads
   `__init__.py` directly by filesystem path regardless.

2. **Add a `skills:` documentation section** (metadata only, no runtime effect):

```yaml
skills:
  bundled:
    - omh-ralplan
    - omh-ralph
    - omh-deep-interview
    - omh-deep-research
    - omh-autopilot
  install_notes: >
    Skills are served from the plugin's own skills/ directory via
    skills.external_dirs in ~/.hermes/config.yaml. After adding the
    external_dirs entry, delete ~/.hermes/.skills_prompt_snapshot.json
    and restart Hermes to see skills in the index.
    Note: local copies in ~/.hermes/skills/omh-*/ shadow external_dirs
    in the system prompt until those copies are removed (deferred).
```

**Acceptance criteria:**
- `plugin.yaml` has no `entry_point:` key
- `plugin.yaml` documents the 5 bundled skills and install note about external_dirs
- Plugin still loads correctly (register() is still the entry point, found by
  `_load_directory_module()` by filesystem convention regardless of plugin.yaml)

---

### Task 5 -- Rewrite `test_init.py`
**Complexity:** Medium
**Dependencies:** Task 3

Delete all 3 existing tests in `test_init.py` -- they test `_install_skills()` logic
that no longer exists. Replace with tests that cover what `register()` actually does:

Required tests (based on R2 Architect C4 and Critic W-NEW-2):

```python
from unittest.mock import MagicMock, patch

def test_register_tools():
    ctx = MagicMock()
    from plugins.omh import register
    register(ctx)
    # Verify both tools registered with correct names and toolset
    registered_tools = {call.args[0] for call in ctx.register_tool.call_args_list}
    assert "omh_state" in registered_tools
    assert "omh_gather_evidence" in registered_tools
    # Verify toolset is "omh" for both
    for call in ctx.register_tool.call_args_list:
        assert call.args[1] == "omh"

def test_register_hooks():
    ctx = MagicMock()
    from plugins.omh import register
    register(ctx)
    registered_hooks = {call.args[0] for call in ctx.register_hook.call_args_list}
    assert "pre_llm_call" in registered_hooks
    assert "on_session_end" in registered_hooks
    assert "pre_tool_call" in registered_hooks

def test_register_no_filesystem_side_effects():
    ctx = MagicMock()
    import shutil
    with patch.object(shutil, "copytree", side_effect=AssertionError("copytree must not be called")):
        from plugins.omh import register
        register(ctx)  # Must not call shutil.copytree

def test_register_no_install_skills():
    # Verify _install_skills no longer exists on the module
    import plugins.omh as omh_module
    assert not hasattr(omh_module, "_install_skills"), \
        "_install_skills() should have been deleted"
```

**Acceptance criteria:**
- All 4 new tests pass with `pytest`
- No test references `_install_skills` (it's deleted)
- No test touches the real `~/.hermes/skills/` directory
- 100% coverage of `register()` (it's short after Task 3)

---

## Risks

**R1 (Low) -- Snapshot cache not cleared after deploy.**
If external_dirs is added but snapshot not cleared, external skills won't appear
in fresh sessions until cache invalidates naturally. Mitigated by Task 2 and
the install note in plugin.yaml.

**R2 (Low) -- Local copies shadow external_dirs.**
While `~/.hermes/skills/omh-*/` copies exist, external_dirs has no effect on
the system prompt. This is the expected state for now and is explicitly documented.
Full effectiveness deferred to the hermes-agent cleanup task.

**R3 (Low) -- Plugin path is user-specific.**
`~/Code/oh-my-hermes/plugins/omh/skills` assumes the repo is at that path.
Users with different checkout locations must adjust this in config.yaml.
Document this limitation in the PR description.

**R4 (Negligible) -- entry_point removal regression.**
`entry_point: plugin` is dead code (verified by Architect against source).
Removing it is safe. The plugin loader (`_load_directory_module()`) finds
`__init__.py` by filesystem path convention, not by this field.

---

## What Was Explicitly Dropped and Why

**DROPPED: `ctx.register_skill()` calls**
Reason: `ctx.register_skill()` docstring explicitly states skills registered
this way are "NOT listed in the system prompt's <available_skills> index -- plugin
skills are opt-in explicit loads only." Adding it would increase complexity with
zero functional benefit for this plugin (no code calls `skill_view("omh:ralplan")`).
(Critic B1, S1; Architect A2 from R1)

**DROPPED: Skill renaming (removing "omh-" prefix from frontmatter `name:` fields)**
Reason: Pure churn with no gain. Without `ctx.register_skill()`, there is no
"omh:omh-ralplan" ugliness to fix. Current names work exactly as needed.
(Critic S3; Architect A1 from R1)

**DEFERRED: Deletion of `~/.hermes/skills/omh-*/` local copies**
Reason: Deleting local copies would make external_dirs the effective skill source,
but requires confidence that all skill_view bare-name callers are covered. R2 Architect
found that `skill_view()` DOES search `get_all_skills_dirs()` which includes external_dirs,
so bare-name calls may work even without local copies. But this needs end-to-end
verification before deleting. Track as a follow-up.
(Critic B3, S4 from R1)

---

## Revision History

- R1: Planner proposed Hybrid D (ctx.register_skill + external_dirs). Architect and Critic
  both REQUEST_CHANGES. Critic identified that ctx.register_skill() is unnecessary and that
  local copies shadow external_dirs.
- R2: Planner revised to drop ctx.register_skill(), renaming, and deletion. Architect and
  Critic both REQUEST_CHANGES on minor documentation/clarity issues (NC-1, NC-2, C1, C4).
  Parent synthesized final plan incorporating all R2 feedback.
