import re
import json
import dataclasses
from dataclasses import dataclass, field
from typing import Any

from jsonpatch import JsonPatch
from jsonpointer import JsonPointer
from mistletoe import Document
from mistletoe.block_token import (
    BlockToken,
    Heading,
    Table,
    TableCell,
    Paragraph,
    Quote,
    BlockCode,
    CodeFence,
    List,
    ListItem,
    HtmlBlock,
)
from mistletoe.markdown_renderer import MarkdownRenderer, BlankLine
from mistletoe.span_token import RawText, Image
from mistletoe.token import Token

from .text import match_content, NoMatch, extract_content_var_filters

MISTUNE_PLUGINS = ['table', 'def_list']

MD_FILTER_VAR = re.compile(r'^\s*{\s*(\w+[\d\w]*)\s*\|\s*md\s*}\s*$')
MD_FILTER_TYPES = (
    Paragraph,
    Quote,
    BlockCode,
    CodeFence,
    List,
    HtmlBlock,
    BlankLine,
)

LIST_FILTER_VAR = re.compile(r'^\s*{\s*(\w+[\d\w]*)\s*\|\s*list\s*}\s*$')

MIXED_FRACTION_VAR = re.compile(r'^\s*{\s*(\w+[\d\w]*)\s*\|\s*mixed_fraction\s*}\s*$')


@dataclass
class MatchResult:
    tokens: int
    vars_map: dict[str, str]


@dataclass
class TableMatchResult(MatchResult):
    table_data: list[Token]


class MatchBase:
    def match_md(
        self,
        tokens: list[BlockToken],
        pos: int,
    ) -> MatchResult | None:
        return match_block_tokens(self.doc, tokens, pos, self.var_filters)

    def patch(
        self, result: MatchResult, json_doc: dict[str, Any], prefix: str
    ) -> dict[str, Any]:
        if self.patch_add:
            return apply_json_patch(self.patch_add, result.vars_map, json_doc, prefix)
        return json_doc


@dataclass
class Match(MatchBase):
    doc: list[BlockToken]
    patch_add: dict[str:Any]
    var_filters: dict[str : str | None]


@dataclass
class FilterMatch(MatchBase):
    doc: list[BlockToken]
    patch_add: dict[str:Any]
    var_filters: dict[str : str | None]
    single_doc: list[BlockToken] | None = None

    def match_md(
        self,
        tokens: list[BlockToken],
        pos: int,
    ) -> MatchResult | None:
        mat = None
        if self.single_doc:
            mat = match_block_tokens(self.single_doc, tokens, pos, self.var_filters)
        if not mat or mat.vars_map['content'] != '1':
            mat = match_block_tokens(self.doc, tokens, pos, self.var_filters)
        return mat


@dataclass
class TableMatch(MatchBase):
    cols: list[str]
    row_patch_add: dict[str:Any] | None
    row_submatch: dict[str : list[FilterMatch | Match]] | None
    row_patch_path: str | None

    @property
    def var_filters(self):
        return dict.fromkeys(f'${n + 1}' for n in range(len(self.cols)))

    def match_md(
        self,
        tokens: list[BlockToken],
        pos: int,
    ) -> TableMatchResult | None:
        return match_table_columns(self.cols, self.row_submatch, tokens, pos)

    def patch(
        self, result: TableMatchResult, json_doc: dict[str, Any], prefix: str
    ) -> dict[str, Any]:
        return apply_table_json_patch(
            self.row_patch_path,
            self.row_patch_add,
            self.row_submatch,
            result,
            json_doc,
            prefix,
        )


@dataclass
class HeadingMatch(MatchBase):
    doc: list[BlockToken]
    patch_path: str | None
    patch_add: dict[str:Any] | None
    var_filters: dict[str : str | None]
    children: list[MatchBase] = field(default_factory=list)
    sections: list[MatchBase] = field(default_factory=list)

    def patch(
        self, result: MatchResult, json_doc: dict[str, Any], prefix: str
    ) -> dict[str, Any]:
        if self.patch_add:
            return apply_json_patch(self.patch_add, result.vars_map, json_doc, prefix)
        return json_doc


class UnknownMatch(Exception):
    pass


class UnknownSubmatch(Exception):
    pass


def is_md_filter_var(match_token):
    """{var|md}"""
    match match_token:
        case Paragraph(children=[RawText(content=text)]):
            if mat := MD_FILTER_VAR.match(text):
                return mat.group(1)


def is_list_filter_var(match_token):
    """- {var|list}"""
    match match_token:
        case List(
            children=[ListItem(children=[Paragraph(children=[RawText(content=text)])])]
        ) if list_var := LIST_FILTER_VAR.match(text):
            return list_var.group(1)


def render_markdown(tokens: list[Token]):
    # render with blank lines intact
    with MarkdownRenderer() as renderer:
        return ''.join(renderer.render(token) for token in tokens)


def match_content_tree(
    vars_map: dict[str, str | None],
    match_token: Token,
    tokens: list[Token],
    token_pos: int,
) -> int:
    """
    returns number of tokens matched by match_token starting
    from tokens[token_pos]. On match updates vars_map in-place.
    """
    if md_var := is_md_filter_var(match_token):
        end = token_pos
        nonblank_end = token_pos
        while end < len(tokens) and isinstance(tokens[end], MD_FILTER_TYPES):
            end += 1
            if not isinstance(tokens[end - 1], BlankLine):
                nonblank_end = end
        if nonblank_end == token_pos:
            return 0
        md = render_markdown(tokens[token_pos:nonblank_end])
        if vars_map[md_var] is None:
            vars_map[md_var] = md
        elif vars_map[md_var] != md:
            return 0
        return end - token_pos

    if list_var := is_list_filter_var(match_token):
        list_vals = [
            render_markdown(c.children).strip() for c in tokens[token_pos].children
        ]
        if vars_map[list_var] is None:
            vars_map[list_var] = list_vals
        elif vars_map[list_var] != list_vals:
            return 0
        return 1

    if not isinstance(tokens[token_pos], type(match_token)):
        return 0

    if isinstance(match_token, Heading) and match_token.level != tokens[token_pos].level:
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

    doc_text = None
    match match_token:
        case RawText(content=text):
            doc_text = tokens[token_pos].content
        case Image(src=text):
            doc_text = tokens[token_pos].src
        case _:
            return 1
    try:
        new_vars = match_content(vars_map, text, doc_text)
    except NoMatch:
        return 0
    vars_map.update(new_vars)
    return 1


def match_block_tokens(
    match_tokens: list[BlockToken],
    tokens: list[BlockToken],
    token_pos: int,
    var_filters: dict[str : str | None],
) -> MatchResult | None:

    vars_map = dict.fromkeys(var_filters)
    i = 0
    for match_token in match_tokens:
        if token_pos + i >= len(tokens):
            return

        if not (
            matched := match_content_tree(vars_map, match_token, tokens, token_pos + i)
        ):
            return
        i += matched

        while token_pos + i < len(tokens) and isinstance(
            tokens[token_pos + i], BlankLine
        ):
            i += 1

    return MatchResult(i, vars_map)


def match_table_columns(
    cols: list[str],
    row_submatch: dict[str : list[FilterMatch | Match]] | None,
    tokens: list[BlockToken],
    pos: int,
) -> MatchResult | None:
    vars_map = {}

    table = tokens[pos]
    if not isinstance(table, Table):
        return

    if len(table.header.children) != len(cols):
        return

    for i, txt in enumerate(cols):
        if not match_content_tree(
            vars_map, TableCell(content=txt), table.header.children, i
        ):
            return

    if row_submatch:
        # FIXME: check that submatch matches
        pass

    return TableMatchResult(1, vars_map, table.children)


def apply_path_vars(path: str, vars_map: dict[str, str]):
    def replace_var(match):
        name = match.group(1)
        if name not in vars_map:
            return match.group(0)
        return vars_map[name].replace('~', '~0').replace('/', '~1')

    return re.sub(r'\$([a-z0-9_]+)', replace_var, path)


def walk_create_object(pos: dict[str, Any] | list[Any], step: str):
    """
    jsonpointer walk, but create missing objects along the way
    """
    if isinstance(pos, list):
        return pos[int(step)]
    return pos.setdefault(step, {})


def append_list_object_path(json_doc: dict[str, Any], path: str) -> int:
    """
    create missing path object(s) and trailing list in-place in json_doc,
    return index of empty object appended to list.
    """
    assert path.endswith('/-/')
    pos = json_doc
    steps = JsonPointer(path).get_parts()
    for step in steps[:-3]:
        pos = walk_create_object(pos, step)
    pos = pos.setdefault(steps[-3], [])
    index = len(pos)
    pos.append({})
    return index


def apply_json_patch(
    patch_add: dict[str:Any],
    vars_map: dict[str, str],
    json_doc: dict[str, Any],
    prefix: str,
) -> dict[str, Any]:
    filled_patch = {}
    for path_template, json_value in patch_add.items():
        jv = json.dumps(json_value)
        path = apply_path_vars(path_template, vars_map)
        for var, val in vars_map.items():
            jv = re.sub(r'(?<!\\)"\$' + var + '"', lambda m: json.dumps(val), jv)
        filled_patch[path] = (json.loads(jv), path_template.endswith('/-'))

    # create missing objects in paths
    prefix_pos = json_doc
    for step in JsonPointer(prefix).get_parts()[:-1]:
        prefix_pos = walk_create_object(prefix_pos, step)

    for path, (json_value, append) in filled_patch.items():
        if path:
            path_pos = prefix_pos
            steps = JsonPointer('/' + path).get_parts()
            for i, step in enumerate(steps):
                if append and i == len(steps) - 2:
                    path_pos = path_pos.setdefault(step, [])
                    break
                path_pos = walk_create_object(path_pos, step)

    operations = [
        {'op': 'add', 'path': prefix + path, 'value': json_value}
        for path, (json_value, _) in filled_patch.items()
    ]
    return JsonPatch(operations).apply(json_doc)


def apply_table_json_patch(
    row_patch_path: str | None,
    row_patch_add: dict[str:Any] | None,
    row_submatch: dict[str : list[FilterMatch | Match]] | None,
    result: TableMatchResult,
    json_doc: dict[str, Any],
    prefix: str,
) -> dict[str, Any]:

    # FIXME: submatching when we should be just patching :-(

    for row in result.table_data:
        vars_map = {
            f'{i + 1}': render_markdown(cell.children).strip()
            for i, cell in enumerate(row.children)
        }
        patch_path = (
            apply_path_vars(row_patch_path, vars_map) + '/' if row_patch_path else ''
        )
        if row_patch_path and row_patch_path.endswith('/-'):
            index = append_list_object_path(json_doc, prefix + patch_path)
            patch_path = patch_path[:-3] + f'/{index}/'

        if row_patch_add:
            json_doc = apply_json_patch(
                row_patch_add, vars_map, json_doc, prefix + patch_path
            )

        for rm, rules in (row_submatch or {}).items():
            assert rm.startswith('$')
            colnum = int(rm[1:]) - 1
            assert 0 <= colnum < len(row.children)
            src = row.children[colnum].children

            for match in rules:
                result = match.match_md(src, 0)
                if not result or result.tokens < len(src):
                    continue

                cell_vars_map = {**vars_map, **result.vars_map}
                if isinstance(match, FilterMatch):
                    src = Document(cell_vars_map.pop('content')).children[0].children

                cell_result = dataclasses.replace(result, vars_map=cell_vars_map)
                json_doc = match.patch(cell_result, json_doc, prefix + patch_path)

                if not isinstance(match, FilterMatch):
                    break
    return json_doc


def parse_match(m):
    if md := m.get('heading_match'):
        doc = Document(md).children
        match = HeadingMatch(
            doc, m.get('patch_path'), m.get('patch_add'), extract_var_filters(doc)
        )
        if children := m.get('children'):
            match.children = parse_matches(children)
        if sections := m.get('sections'):
            match.sections = parse_matches(sections)
        return match

    if md := m.get('match'):
        doc = Document(md).children
        return Match(doc, m.get('patch_add'), extract_var_filters(doc))

    if cols := m.get('table_match'):
        row_submatch = {
            k: parse_submatches(v) for (k, v) in m.get('row_submatch', {}).items()
        }
        return TableMatch(
            cols, m.get('row_patch_add'), row_submatch, m.get('row_patch_path')
        )

    raise UnknownMatch(m)


def parse_matches(matches):
    return [parse_match(m) for m in matches]


def parse_submatch(m):
    match m:
        case {'filter_match': {'singular': str(sflt), 'plural': str(flt)}}:
            sdoc = Document(sflt).children[0].children
            svar_filters = extract_var_filters(sdoc)
            doc = Document(flt).children[0].children
            var_filters = extract_var_filters(doc)
            assert 'content' in var_filters
            assert svar_filters == var_filters
            return FilterMatch(doc, m.get('patch_add'), var_filters, sdoc)

        case {'filter_match': str(flt)}:
            doc = Document(flt).children[0].children
            var_filters = extract_var_filters(doc)
            assert 'content' in var_filters
            return FilterMatch(doc, m.get('patch_add'), var_filters)

        case {'match': str(md)}:
            doc = Document(md).children[0].children
            return Match(doc, m.get('patch_add'), extract_var_filters(doc))

        case _:
            raise UnknownSubmatch(m)


def parse_submatches(matches):
    return [parse_submatch(m) for m in matches]


def extract_var_filters(doc: list[Token]) -> dict[str : str | None]:
    var_filters = {}
    for tok in doc:
        if tok.children:
            var_filters.update(extract_var_filters(tok.children))
        match tok:
            case RawText(content=text):
                var_filters.update(extract_content_var_filters(text))
            case Image(src=text):
                var_filters.update(extract_content_var_filters(text))
    return var_filters
