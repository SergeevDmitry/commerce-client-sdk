# Registry releases

The first source release prepares `@agentic-commerce-lab/ucp-client` for npm and `agentic-commerce-ucp-client` for PyPI. A successful GitHub build is distinct from a registry publication.

## First publication

1. An npm organization owner must grant an authenticated maintainer permission for the `@agentic-commerce-lab` scope. Run `npm publish --access public` from `packages/typescript` after the release checks. No npm publisher login was present during initial setup.
2. A PyPI owner must create a pending trusted publisher for `agentic-commerce-ucp-client`, repository `agentic-commerce-lab/commerce-client-sdk`, workflow `publish.yml`, environment `pypi`. The repository environment must use the intended release reviewers. Alternatively the maintainer may publish the checked wheel and source archive with their own PyPI credentials.
3. Configure npm trusted publishing for that package and workflow once the first npm package exists, using environment `npm`. The manual workflow uses OIDC rather than stored registry tokens.
4. Run the manual **Publish packages** workflow for the reviewed tag, choosing the registry. Each registry runs its own build and publishes exactly version 0.1.0. Keep package versions and the tag aligned for subsequent releases.
5. Verify public registry metadata, install from the public registry in a clean directory, and run the import/client smoke test. Only then change package availability copy and list the npm/PyPI install commands on the website.

The publication workflow requests `id-token: write` only in the selected publishing job. It never runs on pull requests. Trusted publisher configuration and any required terms acceptance must be performed by the account owner; source and package checks can run without those privileges.

## Local package checks

```sh
npm ci --prefix packages/typescript
npm run build --prefix packages/typescript
npm test --prefix packages/typescript
(cd packages/typescript && npm pack)
python -m build packages/python
python -m twine check packages/python/dist/*
```

No token or private key belongs in this repository. Signing tests generate temporary keys in memory.
