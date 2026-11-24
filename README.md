# semantic-md

Semantic Markdown uses YAML schemas to convert Markdown documents to JSON.
Learn more at [semanticmd.org](https://semanticmd.org).

## Converting Markdown to JSON

`smd json` converts a Markdown document to JSON, using the schema named in the
document's front matter:

```sh
smd json input.md output.json
```

You can instead provide a schema explicitly with `--schema`:

```sh
smd json input.md output.json --schema schema.yaml
```

## Converting JSON to Markdown

`smd md` uses a schema's match patterns and JSON patches to construct Markdown,
then verifies that converting the result back to JSON produces the input:

```sh
smd md input.json output.md --schema schema.yaml
```

The generated Markdown includes front matter pointing to the schema, so it can
be converted back with `smd json output.md output.json`.

The converter escapes plain text inserted into Markdown patterns. Values captured
with `|md` or `|list`, and values captured directly from table cells, are treated
as Markdown rather than plain text. Not all JSON values or schemas can be rendered;
if no candidate passes the conversion-back check, `smd md` reports an error.

The output is a valid Markdown representation, not necessarily the original
document. A schema may discard formatting or other source details, and inverse
rendering may choose a canonical form (for example, a particular fraction or
table layout). Consequently, some Markdown documents will not round-trip
exactly even when their JSON output does.
