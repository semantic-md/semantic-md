from mistletoe import Document
from mistletoe.block_token import BlockToken

from .read import Schema
from .text import NoMatch

def to_json(doc: Document, schema: Schema):
    doc_pos = 0
    heading_level = 0
    schema_stack = [schema.sections]
    json_doc = {}

    while doc_pos < len(doc.children):
        for match in schema_stack[-1]:
            if result := match.match_md(doc.children, doc_pos):
                doc_pos += result.tokens
                json_doc = match.patch(result.vars_map, json_doc)
                break
        else:
            raise NoMatch(doc.children[doc_pos])

    breakpoint()
    return out
