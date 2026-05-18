import os
import json

from yaml import safe_load

from semantic_md import match, convert

HERE = os.path.split(__file__)[0]


def test1():
    f = open(os.path.join(HERE, 'example.md')).read()
    front, body = match.md_parse_front_matter(f)
    assert front['semantic-md'] == 'datadict.yml'

    schema = safe_load(open(os.path.join(HERE, 'datadict.yml')))

    parsed = match.md_parse_body(body, schema)

    s = open(os.path.join(HERE, 'datadict.yml')).read()
    schema = match.Schema.read(s)

    out = convert.to_json(parsed, schema)
    assert out == json.load(open(os.path.join(HERE, 'example.json')))
