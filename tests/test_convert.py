import json
import os

import pytest
from click.testing import CliRunner
from yaml import safe_load

from semantic_md import convert
from semantic_md.cli import cli

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


@pytest.mark.parametrize('name', ['recipe', 'datadict'])
def test_json_to_markdown_round_trips(name):
    with open(os.path.join(HERE, f'{name}.yaml')) as schema_file:
        schema = convert.Schema.read(schema_file.read())
    with open(os.path.join(HERE, f'{name}.json')) as json_file:
        expected = json.load(json_file)

    markdown = convert.to_markdown(expected, schema)

    assert convert.to_json(convert.md_parse_body(markdown, schema), schema) == expected


def test_md_command_output_can_be_converted_back(tmp_path):
    schema_path = tmp_path / 'recipe.yaml'
    source_path = tmp_path / 'recipe.json'
    markdown_path = tmp_path / 'recipe.md'
    destination_path = tmp_path / 'result.json'
    with open(os.path.join(HERE, 'recipe.yaml')) as schema_file:
        schema_path.write_text(schema_file.read(), encoding='utf-8')
    with open(os.path.join(HERE, 'recipe.json')) as json_file:
        source_path.write_text(json_file.read(), encoding='utf-8')
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ['md', str(source_path), str(markdown_path), '--schema', str(schema_path)],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(cli, ['json', str(markdown_path), str(destination_path)])
    assert result.exit_code == 0, result.output
    assert json.loads(destination_path.read_text(encoding='utf-8')) == json.loads(
        source_path.read_text(encoding='utf-8')
    )
