import re
from dataclasses import dataclass
from typing import Any, Optional

from mistletoe import Document
from yaml import safe_load

MISTUNE_PLUGINS = ['table', 'def_list']

class InputError(Exception):
    pass

def md_parse_front_matter(s):
    parts = re.split(r'^---\s*$', s, 2, flags=re.MULTILINE)
    if len(parts) != 3 or parts[0].strip() or '\n' not in parts[1]:
        raise InputError('expected yaml front matter not found')

    front = safe_load(parts[1])
    body = parts[2]

    return front, body


def md_parse_body(body, schema):
    return Document(body)


class MatchBase:
    pass

@dataclass
class Match(MatchBase):
    md: str
    patch_add: dict[str: Any]
    vars_: list[str]

@dataclass
class TableMatch(MatchBase):
    md: str
    row_patch_add: dict[str: Any]
    row_submatch: dict[str: Any] | None = None

@dataclass
class ListMatch(MatchBase):
    "vars_ = ['listval']"
    md: str
    list_patch_add: dict[str: Any]

@dataclass
class StartMatch(MatchBase):
    md: str
    patch_path: str | None
    patch_add: dict[str: Any] | None
    vars_: list[str] | None
    children: list[MatchBase] | None = None
    sections: list[MatchBase] | None = None

class UnknownMatch(Exception):
    pass

def parse_match(m):
    if md := m.get('start_match'):
        match = StartMatch(md, m.get('patch_path'), m.get('patch_add'), m.get('vars'))
        if children := m.get('children'):
            match.children = parse_matches(children)
        if sections := m.get('sections'):
            match.sections = parse_matches(sections)
        return match
    if md := m.get('match'):
        return Match(md, m.get('patch_add'), m.get('vars'))
    if md := m.get('table_match'):
        return TableMatch(md, m['row_patch_add'], m.get('row_submatch'))
    if md := m.get('list_match'):
        return ListMatch(md, m['list_patch_add'])
    raise UnknownMatch(m)


def parse_matches(matches):
    return [parse_match(m) for m in matches]

class Schema:
    @classmethod
    def read(cls, yaml_str):
        y = safe_load(yaml_str)

        assert set(y) == {'sections', 'semantic-md-version'}
        schema = cls()
        schema.sections = parse_matches(y['sections'])

        return schema
