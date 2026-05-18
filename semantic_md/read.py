import re
import json
from dataclasses import dataclass
from typing import Any, Optional

from jsonpatch import JsonPatch
from jsonpointer import JsonPointer
from mistletoe import Document
from mistletoe.block_token import (
    BlockToken, Table, TableCell, Paragraph, Quote, BlockCode, CodeFence,
    List, ListItem, HtmlBlock,
)
from mistletoe.markdown_renderer import MarkdownRenderer, BlankLine
from mistletoe.span_token import RawText
from mistletoe.token import Token
from yaml import safe_load

from .text import match_content, NoMatch

MISTUNE_PLUGINS = ['table', 'def_list']

MD_FILTER_VAR = re.compile(r'^\s*{\s*(\w+[\d\w]*)\s*\|\s*md\s*}\s*$')
MD_FILTER_TYPES = (
    Paragraph, Quote, BlockCode, CodeFence, List, HtmlBlock, BlankLine,
)

LIST_FILTER_VAR = re.compile(r'^\s*{\s*(\w+[\d\w]*)\s*\|\s*list\s*}\s*$')

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
    # context manager required for creation of BlankLine, etc.
    with MarkdownRenderer() as renderer:
        return Document(body)


@dataclass
class MatchResult:
    tokens: int
    vars_map: dict[str, str]

@dataclass
class TableMatchResult(MatchResult):
    table_data: list[Token]


def is_md_filter_var(match_token):
    """{var|md}"""
    if (
        isinstance(match_token, Paragraph) and
        len(match_token.children) == 1 and
        (md_var := MD_FILTER_VAR.match(match_token.children[0].content))
    ):
        return md_var.group(1)

def is_list_filter_var(match_token):
    """- {var|list}"""
    if (
        isinstance(match_token, List) and
        len(match_token.children) == 1 and
        isinstance(li := match_token.children[0], ListItem) and
        len(li.children) == 1 and
        isinstance(p := li.children[0], Paragraph) and
        len(p.children) == 1 and
        (list_var := LIST_FILTER_VAR.match(p.children[0].content))
    ):
        return list_var.group(1)

def match_content_tree(
    vars_map: dict[str, str|None], match_token: Token,
    tokens: list[Token], token_pos: int,
) -> int:
    """
    returns number of tokens matched by match_token starting
    from tokens[token_pos]. On match updates vars_map in-place.
    """
    if md_var := is_md_filter_var(match_token):
        nonblank = token_pos
        for i in range(token_pos, len(tokens)):
            if not isinstance(tokens[i], MD_FILTER_TYPES):
                break
            if not isinstance(tokens[i], BlankLine):
                nonblank = i
        with MarkdownRenderer() as renderer:
            md = ''.join(
                renderer.render(tokens[j]) for j in range(token_pos, nonblank + 1)
            )
        if vars_map[md_var] is None:
            vars_map[md_var] = md
        elif vars_map[md_var] != md:
            return 0
        return i - token_pos

    if list_var := is_list_filter_var(match_token):
        # FIXME: handle non-single-paragraph lists
        list_vals = [
            c.children[0].children[0].content
            for c in tokens[token_pos].children
        ]
        if vars_map[list_var] is None:
            vars_map[list_var] = list_vals
        elif vars_map[list_var] != listvals:
            return 0
        return 1

    if not isinstance(tokens[token_pos], type(match_token)):
        return 0

    if mtoks := match_token.children:
        toks = tokens[token_pos].children
        pos = 0
        for mt in mtoks:
            if pos > len(toks):
                return 0
            if not (matched := match_content_tree(vars_map, mt, toks, pos)):
                return 0
            pos += matched
        if pos < len(toks):
            return 0

    if isinstance(match_token, RawText) and hasattr(match_token, "content"):
        try:
            new_vars = match_content(
                vars_map, match_token.content, tokens[token_pos].content)
        except NoMatch:
            return 0
        vars_map.update(new_vars)
    return 1

def match_block_tokens(
    match_tokens: list[BlockToken], tokens: list[BlockToken],
    token_pos: int, vars_: list[str],
) -> MatchResult | None:

    vars_map = {var: None for var in vars_ or []}
    i = 0
    for match_token in match_tokens:
        if token_pos + i >= len(tokens):
            return

        if not (matched := match_content_tree(
            vars_map, match_token, tokens, token_pos + i
        )):
            return
        i += matched

        while token_pos + i < len(tokens) and isinstance(
            tokens[token_pos + i], BlankLine
        ):
            i += 1

    return MatchResult(i, vars_map)

def match_table_columns(
    cols: list[str], row_submatch: dict[str: Any] | None,
    tokens: list[BlockToken], pos: int,
) -> MatchResult | None:
    vars_map = {}

    table = tokens[pos]
    if not isinstance(table, Table):
        return

    if len(table.header.children) != len(cols):
        return

    try:
        for i, txt in enumerate(cols):
            match_content_tree(
                vars_map, TableCell(content=txt), table.header.children, i)
    except NoMatch:
        return

    if row_submatch:
        # FIXME: check that submatch matches
        pass

    return TableMatchResult(1, vars_map, table.children)

def apply_path_vars(path: str, vars_map: dict[str, str]):
    for var, val in vars_map.items():
        # FIXME: jsonpath escaping for val?
        path = re.sub(r'\$' + var + r'\b', lambda m: val, path)
    return path

def apply_json_patch(
    patch_add: dict[str: Any], vars_map: dict[str, str], json_doc: dict[str, Any],
    prefix: str
) -> dict[str, Any]:
    filled_patch = {}
    for path, json_value in patch_add.items():
        jv = json.dumps(json_value)
        path = apply_path_vars(path, vars_map)
        for var, val in vars_map.items():
            jv = re.sub(
                r'(?<!\\)"\$' + var + '"',
                lambda m: json.dumps(val),
                jv
            )
        filled_patch[path] = json.loads(jv)

    # create missing objects in paths
    prefix_pos = json_doc
    for step in JsonPointer(prefix).get_parts()[:-1]:
        prefix_pos = prefix_pos.setdefault(step, {})
    for path, json_value in filled_patch.items():
        if path:
            path_pos = prefix_pos
            steps = JsonPointer('/' + path).get_parts()
            for i, step in enumerate(steps):
                if steps[-1:] == ['-'] and i == len(steps) - 2:
                    path_pos = path_pos.setdefault(step, [])
                    break
                path_pos = path_pos.setdefault(step, {})

    operations = [
        {'op': 'add', 'path': prefix + path, 'value': json_value}
        for path, json_value in filled_patch.items()
    ]
    return JsonPatch(operations).apply(json_doc)

def apply_table_json_patch(
    row_patch_add: dict[str: Any], row_submatch: dict[str: Any] | None,
    result: TableMatchResult, json_doc: dict[str, Any], prefix: str,
) -> dict[str, Any]:
    # FIXME: assuming cells are always a single RawText
    for row in result.table_data:
        vars_map = {
            f'{i + 1}': cell.children[0].content
            for i, cell in enumerate(row.children)
        }
        for rm, rules in (row_submatch or {}).items():
            src = apply_path_vars(rm, vars_map)
            for rule in rules:
                if flt := rule.get('filter_match'):
                    try:
                        content_vars = match_content(
                            {'content': None}, flt, src)
                    except NoMatch:
                        continue
                    if cmatch := content_vars['content']:
                        src = cmatch
                    json_doc = apply_json_patch(
                        rule['patch_add'], vars_map, json_doc, prefix)

                if mat := rule.get('match'):
                    mvars = {var: None for var in rule['vars'] or []}
                    try:
                        mvars = match_content(mvars, mat, src)
                    except NoMatch:
                        continue
                    json_doc = apply_json_patch(
                        rule['patch_add'], {**vars_map, **mvars}, json_doc, prefix)

        json_doc = apply_json_patch(row_patch_add, vars_map, json_doc, prefix)
    return json_doc


class MatchBase:
    def match_md(self, tokens: list[BlockToken], pos: int,
    ) -> MatchResult | None:
        return match_block_tokens(self.doc, tokens, pos, self.vars_)

    def patch(
        self, result: MatchResult, json_doc: dict[str, Any], prefix: str
    ) -> dict[str, Any]:
        if self.patch_add:
            return apply_json_patch(self.patch_add, result.vars_map, json_doc, prefix)
        return json_doc

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

    def match_md(self, tokens: list[BlockToken], pos: int,
    ) -> TableMatchResult | None:
        return match_table_columns(self.cols, self.row_submatch, tokens, pos)

    def patch(
        self, result: TableMatchResult, json_doc: dict[str, Any], prefix: str
    ) -> dict[str, Any]:
        return apply_table_json_patch(
            self.row_patch_add, self.row_submatch, result, json_doc, prefix,
        )

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

    raise UnknownMatch(m)


def parse_matches(matches):
    return [parse_match(m) for m in matches]

class Schema:
    @classmethod
    def read(cls, yaml_str):
        y = safe_load(yaml_str)

        assert set(y) == {'sections', 'semantic-md-version'}
        schema = cls()
        schema.children = parse_matches(y.get('children', []))
        schema.sections = parse_matches(y.get('sections', []))

        return schema
