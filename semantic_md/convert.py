import re

from mistletoe import Document
from mistletoe.block_token import Heading
from mistletoe.markdown_renderer import BlankLine, MarkdownRenderer
from yaml import safe_load

from .match import HeadingMatch, append_list_object_path, apply_path_vars, parse_matches
from .text import NoMatch


class Schema:
    @classmethod
    def read(cls, yaml_str):
        y = safe_load(yaml_str)

        schema = cls()
        schema.definition = y
        schema.children = parse_matches(y.get('children', []))
        schema.sections = parse_matches(y.get('sections', []))

        return schema


class MatchFrame:
    def __init__(self, schema: Schema | HeadingMatch):
        self.schema = schema
        # sections repeat, children only match once
        self.children = iter(schema.children)

    def __iter__(self):
        yield from self.children
        if self.schema.sections:
            yield from self.schema.sections


def to_json(doc: Document, schema: Schema):
    doc_pos = 0
    heading_level = 0
    schema_stack = [MatchFrame(schema)]
    prefix_stack = ['/']
    json_doc = {}

    while doc_pos < len(doc.children):
        tok = doc.children[doc_pos]
        if isinstance(tok, BlankLine):
            doc_pos += 1
            continue

        if isinstance(tok, Heading):
            while tok.level <= heading_level:
                schema_stack.pop()
                prefix_stack.pop()
                heading_level -= 1

        for match in schema_stack[-1]:
            if result := match.match_md(doc.children, doc_pos):
                doc_pos += result.tokens
                if isinstance(match, HeadingMatch):
                    heading = match.doc[0]
                    # FIXME: enforce these
                    assert isinstance(heading, Heading)
                    assert heading_level + 1 == heading.level
                    heading_level = heading.level
                    schema_stack.append(MatchFrame(match))
                    patch_path = (
                        apply_path_vars(match.patch_path, result.vars_map) + '/'
                        if match.patch_path
                        else ''
                    )
                    if match.patch_path and match.patch_path.endswith('/-'):
                        index = append_list_object_path(
                            json_doc, ''.join(prefix_stack + [patch_path])
                        )
                        patch_path = patch_path[:-3] + f'/{index}/'
                    prefix_stack.append(patch_path)

                json_doc = match.patch(result, json_doc, ''.join(prefix_stack))
                break
        else:
            with MarkdownRenderer() as renderer:
                raise NoMatch(
                    f'line {doc.children[doc_pos].line_number}\n'
                    + renderer.render(doc.children[doc_pos])
                )

    return json_doc


def to_markdown(json_doc: dict, schema: Schema) -> str:
    from .inverse import to_markdown as render_markdown

    return render_markdown(json_doc, schema)


class InputError(Exception):
    pass


def md_parse_front_matter(s, allow_missing=False):
    parts = re.split(r'^---\s*$', s, 2, flags=re.MULTILINE)
    if len(parts) != 3 or parts[0].strip() or '\n' not in parts[1]:
        if allow_missing:
            return {}, s
        raise InputError('expected yaml front matter not found')

    front = safe_load(parts[1])
    body = parts[2]

    return front, body


def md_parse_body(body, schema):
    # context manager required for creation of BlankLine, etc.
    with MarkdownRenderer():
        return Document(body)
