import re
import json
from dataclasses import dataclass
from typing import Any, Optional

from jsonpatch import JsonPatch
from mistletoe import Document
from mistletoe.block_token import BlockToken
from yaml import safe_load

from .text import match_content, NoMatch

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


@dataclass
class MatchResult:
    tokens: int
    vars_map: dict[str, str]

def match_block_tokens(
    match_tokens: list[BlockToken], tokens: list[BlockToken], pos: int,
    vars_: list[str],
) -> MatchResult | None:

    vars_map = {var: None for var in vars_}
    for i, match_token in enumerate(match_tokens):
        try:
            token = tokens[pos + i]
        except IndexError:
            return
        if type(match_token) != type(token):
            return

        mtoks = match_token.children
        toks = token.children
        if len(mtoks) != len(toks):
            return

        try:
            for mt, t in zip(mtoks, toks):
                if type(mt) != type(t):
                    return
                new_vars = match_content(vars_map, mt.content, t.content)
                vars_map.update(new_vars)
        except NoMatch:
            return

    return MatchResult(len(tokens), vars_map)

def apply_json_patch(
    patch_add: dict[str: Any], vars_map: dict[str, str], json_doc: dict[str, Any],
) -> dict[str, Any]:
    filled_patch = {}
    for path, json_value in patch_add.items():
        jv = json.dumps(json_value)
        for var, val in vars_map.items():
            path = re.sub(r'\$' + var + r'\b', val, path)
            jv = re.sub(r'(?<!\\)"\$' + var + '"', '"' + val + '"', jv)
        filled_patch[path] = json.loads(jv)

    return JsonPatch([
        {'op': 'add', 'path': path, 'value': json_value}
        for path, json_value in filled_patch.items()
    ]).apply(json_doc)

class MatchBase:
    def match_md(self, tokens: list[BlockToken], pos: int,
            ) -> MatchResult | None:
        return match_block_tokens(self.doc, tokens, pos, self.vars_)

    def patch(self, vars_map: dict[str, str], json_doc: dict[str, Any]) -> None:
        return apply_json_patch(self.patch_add, vars_map, json_doc)

@dataclass
class Match(MatchBase):
    doc: list[BlockToken]
    patch_add: dict[str: Any]
    vars_: list[str]

@dataclass
class TableMatch(MatchBase):
    cols: list[str]
    row_patch_add: dict[str: Any]
    row_submatch: dict[str: Any] | None = None

    @property
    def vars_(self):
        return [f'${n + 1}' for n in range(len(self.cols))]

@dataclass
class ListMatch(MatchBase):
    doc: list[BlockToken]
    list_patch_add: dict[str: Any]

    @property
    def vars_(self):
        return ['listval']

@dataclass
class HeadingMatch(MatchBase):
    doc: list[BlockToken]
    patch_path: str | None
    patch_add: dict[str: Any] | None
    vars_: list[str] | None
    children: list[MatchBase] | None = None
    sections: list[MatchBase] | None = None

class UnknownMatch(Exception):
    pass

def parse_match(m):
    if md := m.get('heading_match'):
        doc = Document(md).children
        match = HeadingMatch(doc, m.get('patch_path'), m.get('patch_add'), m.get('vars'))
        if children := m.get('children'):
            match.children = parse_matches(children)
        if sections := m.get('sections'):
            match.sections = parse_matches(sections)
        return match

    if md := m.get('match'):
        doc = Document(md).children
        return Match(doc, m.get('patch_add'), m.get('vars'))

    if cols := m.get('table_match'):
        return TableMatch(cols, m['row_patch_add'], m.get('row_submatch'))

    if md := m.get('list_match'):
        doc = Document(md).children
        return ListMatch(doc, m['list_patch_add'])

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
