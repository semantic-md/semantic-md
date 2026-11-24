import json
import os

import pytest
from click.testing import CliRunner
from mistletoe import Document
from mistletoe.html_renderer import HTMLRenderer
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


def test_json_command_accepts_missing_front_matter_with_schema(tmp_path):
    schema_path = tmp_path / 'schema.yaml'
    source_path = tmp_path / 'input.md'
    destination_path = tmp_path / 'output.json'
    schema_path.write_text(
        'children:\n- match: "{value}"\n  patch_add: {value: $value}\n',
        encoding='utf-8',
    )
    source_path.write_text('Some content\n', encoding='utf-8')

    result = CliRunner().invoke(
        cli,
        ['json', str(source_path), str(destination_path), '-s', str(schema_path)],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(destination_path.read_text(encoding='utf-8')) == {
        'value': 'Some content'
    }


def test_inverse_renders_markdown_blocks_and_ordered_list():
    schema = convert.Schema.read("""
children:
  - match: "{ description | md }"
    patch_add: {description: $description}
  - match: |
      ## Steps

      1. { steps | list }
    patch_add: {steps: $steps}
""")
    expected = {
        'description': 'First paragraph.\n\n> A quote.\n\n```\ncode\n```\n',
        'steps': [f'Step {number}' for number in range(1, 12)],
    }

    markdown = convert.to_markdown(expected, schema)

    assert '11. Step 11' in markdown
    assert convert.to_json(convert.md_parse_body(markdown, schema), schema) == expected


def test_inverse_renders_table_with_pipe_in_cell():
    schema = convert.Schema.read("""
children:
  - table_match: [Name, Value]
    row_patch_add:
      rows/-: {name: $1, value: $2}
""")
    expected = {'rows': [{'name': 'left | right', 'value': 'a value'}]}

    markdown = convert.to_markdown(expected, schema)

    assert r'left \| right' in markdown
    assert convert.to_json(convert.md_parse_body(markdown, schema), schema) == expected


def test_inverse_reports_when_target_cannot_round_trip():
    schema = convert.Schema.read("""
children:
  - match: "{value}"
    patch_add: {value: $value}
""")
    with pytest.raises(convert.NoMatch, match='could not produce Markdown'):
        convert.to_markdown({'value': 'test', 'extra': True}, schema)


@pytest.mark.parametrize(
    'value',
    [
        'a *bold* and _emphasis_',
        '[a link](https://example.com)',
        'A #',
        'Text &amp; <tag>',
        r'back\slash and `code`',
    ],
)
def test_inverse_escapes_heading_text(value):
    schema = convert.Schema.read("""
sections:
  - heading_match: "# {name}"
    patch_path: items/-
    patch_add: {name: $name}
""")
    expected = {'items': [{'name': value}]}
    markdown = convert.to_markdown(expected, schema)

    assert convert.to_json(convert.md_parse_body(markdown, schema), schema) == expected


def test_inverse_heading_renders_special_characters_as_text():
    schema = convert.Schema.read("""
sections:
  - heading_match: "# {name}"
    patch_path: items/-
    patch_add: {name: $name}
""")
    markdown = convert.to_markdown(
        {'items': [{'name': 'x *strong* <em>Hi</em>'}]}, schema
    )

    with HTMLRenderer() as renderer:
        html = renderer.render(Document(markdown))

    assert html == '<h1>x *strong* &lt;em&gt;Hi&lt;/em&gt;</h1>\n'


@pytest.mark.parametrize('value', ['- item', '1. item', '> quoted', '---', 'a & b'])
def test_inverse_escapes_paragraph_block_markers(value):
    schema = convert.Schema.read("""
children:
  - match: "{value}"
    patch_add: {value: $value}
""")
    expected = {'value': value}
    markdown = convert.to_markdown(expected, schema)

    assert convert.to_json(convert.md_parse_body(markdown, schema), schema) == expected


def test_inverse_escapes_image_alt_and_destination():
    schema = convert.Schema.read("""
children:
  - match: "![{alt}]({url})"
    patch_add: {alt: $alt, url: $url}
""")
    expected = {
        'alt': '[a] *photo*',
        'url': 'https://example.com/a (b)?x=1&y=2#top',
    }

    markdown = convert.to_markdown(expected, schema)

    assert convert.to_json(convert.md_parse_body(markdown, schema), schema) == expected


def test_inverse_preserves_table_cell_markdown():
    schema = convert.Schema.read("""
children:
  - table_match: [Name, Value]
    row_patch_add:
      rows/-: {name: $1, value: $2}
""")
    expected = {'rows': [{'name': '*italic*', 'value': r'a | b'}]}

    markdown = convert.to_markdown(expected, schema)

    assert '*italic*' in markdown
    assert convert.to_json(convert.md_parse_body(markdown, schema), schema) == expected


def test_inverse_preserves_multiline_list_item():
    schema = convert.Schema.read("""
children:
  - match: |
      1. {steps|list}
    patch_add: {steps: $steps}
""")
    expected = {'steps': ['First line\nSecond line', '**Next**']}

    markdown = convert.to_markdown(expected, schema)

    assert '**Next**' in markdown
    assert convert.to_json(convert.md_parse_body(markdown, schema), schema) == expected


def test_md_command_does_not_overwrite_destination_when_rendering_fails(tmp_path):
    schema_path = tmp_path / 'schema.yaml'
    source_path = tmp_path / 'input.json'
    destination_path = tmp_path / 'output.md'
    schema_path.write_text(
        'children:\n- match: "{value}"\n  patch_add: {value: $value}\n',
        encoding='utf-8',
    )
    source_path.write_text('{"value": "test", "extra": true}', encoding='utf-8')
    destination_path.write_text('existing content', encoding='utf-8')

    result = CliRunner().invoke(
        cli,
        ['md', str(source_path), str(destination_path), '-s', str(schema_path)],
    )

    assert result.exit_code != 0
    assert 'could not produce Markdown' in result.output
    assert destination_path.read_text(encoding='utf-8') == 'existing content'
