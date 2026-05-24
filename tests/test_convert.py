import os
import json

from yaml import safe_load
import pytest

from semantic_md import convert

HERE = os.path.split(__file__)[0]


@pytest.mark.parametrize('name', ['datadict', 'recipe'])
def test_convert(name):
    f = open(os.path.join(HERE, f'{name}.md')).read()
    front, body = convert.md_parse_front_matter(f)
    assert front['semantic-md'] == f'{name}.yaml'

    schema = safe_load(open(os.path.join(HERE, f'{name}.yaml')))

    parsed = convert.md_parse_body(body, schema)

    s = open(os.path.join(HERE, f'{name}.yaml')).read()
    schema = convert.Schema.read(s)

    out = convert.to_json(parsed, schema)
    assert out == json.load(open(os.path.join(HERE, f'{name}.json')))
