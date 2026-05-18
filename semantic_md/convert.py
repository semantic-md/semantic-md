from mistletoe import Document
from mistletoe.block_token import BlockToken, Heading
from mistletoe.markdown_renderer import MarkdownRenderer, BlankLine

from .read import Schema, HeadingMatch, apply_path_vars
from .text import NoMatch

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
                json_doc = match.patch(result, json_doc, ''.join(prefix_stack))

                if isinstance(match, HeadingMatch):
                    heading = match.doc[0]
                    # FIXME: enforce these
                    assert isinstance(heading, Heading)
                    assert heading_level + 1 == heading.level
                    heading_level = heading.level
                    schema_stack.append(MatchFrame(match))
                    prefix_stack.append(
                        apply_path_vars(match.patch_path, result.vars_map) + '/'
                        if match.patch_path else ''
                    )
                break
        else:
            with MarkdownRenderer() as renderer:
                raise NoMatch(
                    f'line {doc.children[doc_pos].line_number}\n'
                    + renderer.render(doc.children[doc_pos])
                )

    return json_doc
