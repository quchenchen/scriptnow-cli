"""The progressively loaded Skill must remain a self-contained installable bundle."""
from pathlib import Path
import re


SKILL_ROOT = Path(__file__).resolve().parents[1] / 'cli_anything/scriptnow/skills'


def test_skill_local_references_resolve_inside_bundle():
    reached = set()
    pending = [SKILL_ROOT / 'SKILL.md']
    while pending:
        current = pending.pop()
        if current in reached:
            continue
        reached.add(current)
        for target in re.findall(r'\]\(([^)]+)\)', current.read_text()):
            if '://' in target or target.startswith('#'):
                continue
            resolved = (current.parent / target.split('#')[0]).resolve()
            assert resolved.is_relative_to(SKILL_ROOT.resolve()), target
            assert resolved.is_file(), target
            if resolved.suffix == '.md':
                pending.append(resolved)
    references = set((SKILL_ROOT / 'references').glob('*.md'))
    assert references <= reached
