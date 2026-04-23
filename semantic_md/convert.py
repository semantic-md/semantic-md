from mistletoe import Document
from mistletoe.block_token import BlockToken, Heading

from .read import Schema, HeadingMatch
from .text import NoMatch

def to_json(doc: Document, schema: Schema):
    doc_pos = 0
    heading_level = 0
    schema_stack = [schema.sections]
    json_doc = {}

    while doc_pos < len(doc.children):
        if isinstance(tok := doc.children[doc_pos], Heading):
            while tok.level <= heading_level:
                schema_stack.pop()
                heading_level -= 1

        for match in schema_stack[-1]:
            if result := match.match_md(doc.children, doc_pos):
                doc_pos += result.tokens
                json_doc = match.patch(result, json_doc)

                if isinstance(match, HeadingMatch):
                    heading = match.doc[0]
                    # FIXME: enforce these
                    assert isinstance(heading, Heading)
                    assert heading_level + 1 == heading.level
                    heading_level = heading.level
                    schema_stack.append(match.children)
                break
        else:
            raise NoMatch(doc.children[doc_pos])
    breakpoint()

    return json_doc
