# Contributing to Docgrain

Thanks for contributing. Docgrain is pre-alpha; small, well-tested changes are especially valuable.

## Before opening a pull request

1. Open an issue for changes that alter the data contract, API shape, provider interfaces or pipeline behavior.
2. Keep pull requests focused and explain user-visible behavior.
3. Add or update tests. Parser changes require fixtures that demonstrate the change.
4. Never commit API keys, real customer files, vector indexes, database dumps or generated document artifacts.

## Development expectations

- Format and lint code before submitting it.
- Preserve existing metadata when transforming sections and chunks.
- Avoid provider-specific concepts in the domain package.
- Document new environment variables in `.env.example`.
- Add an ADR under `docs/adr/` for consequential architecture decisions.

## Reporting issues

Please include the document type, an anonymized/minimal reproducible fixture when permitted, expected result, actual result and environment details. Do not upload confidential documents to public issues.
