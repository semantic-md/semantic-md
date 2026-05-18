import os
import json

from yaml import safe_load

from semantic_md import read, convert

HERE = os.path.split(__file__)[0]

def test1():
    f = open(os.path.join(HERE, 'example.md')).read()
    front, body = read.md_parse_front_matter(f)
    assert front['semantic-md'] == 'datadict.yml'

    schema = safe_load(open(os.path.join(HERE, 'datadict.yml')))

    parsed = read.md_parse_body(body, schema)

    s = open(os.path.join(HERE, 'datadict.yml')).read()
    schema = read.Schema.read(s)

    out = convert.to_json(parsed, schema)
    assert out == json.load(open(os.path.join(HERE, 'example.json')))
