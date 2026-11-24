import json
import os

import pytest
from yaml import safe_load

from semantic_md import convert

HERE = os.path.split(__file__)[0]


@pytest.mark.parametrize('name', ['datadict', 'recipe'])
def test_convert(name):
    with open(os.path.join(HERE, f'{name}.md')) as markdown_file:
        markdown = markdown_file.read()
    front, body = convert.md_parse_front_matter(markdown)
    assert front['semantic-md'] == f'{name}.yaml'

    with open(os.path.join(HERE, f'{name}.yaml')) as yaml_file:
        schema = safe_load(yaml_file)

    parsed = convert.md_parse_body(body, schema)

    with open(os.path.join(HERE, f'{name}.yaml')) as yaml_file:
        schema_text = yaml_file.read()
    schema = convert.Schema.read(schema_text)

    out = convert.to_json(parsed, schema)
    with open(os.path.join(HERE, f'{name}.json')) as json_file:
        expected = json.load(json_file)
    assert out == expected
