import re

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
