# semantic-md

Semantic Markdown uses YAML schemas to convert Markdown documents to JSON.

## Converting JSON to Markdown

`smd md` uses a schema's match patterns and JSON patches to construct Markdown,
then verifies that converting the result back to JSON produces the input:

```sh
smd md input.json output.md --schema schema.yaml
```

The generated Markdown includes front matter pointing to the schema, so it can
be converted back with `smd json output.md output.json`.

The output is a valid Markdown representation, not necessarily the original
document. A schema may discard formatting or other source details, and inverse
rendering may choose a canonical form (for example, a particular fraction or
table layout). Consequently, some Markdown documents will not round-trip
exactly even when their JSON output does.
