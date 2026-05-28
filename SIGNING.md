# Code signing (SignPath Foundation)

Windows release binaries are (or will be) Authenticode-signed for free via the
[SignPath Foundation](https://signpath.org/) open-source program. This removes the
Windows SmartScreen "unknown publisher" warning.

## One-time setup (maintainer)

1. **Apply** at <https://signpath.org/> for the SignPath Foundation free OSS
   program, using this repository (public + MIT-licensed).
2. After approval, in the SignPath dashboard create:
   - a **Project** with slug `analogue-3d-utility`
   - an **Artifact Configuration** for the uploaded build artifact
   - a **Signing Policy** with slug `release-signing`
   - link this GitHub repo as a trusted build system / connect the GitHub app
3. Generate a **CI user API token**.
4. In GitHub → *Settings → Secrets and variables → Actions*:
   - add secret **`SIGNPATH_API_TOKEN`**
   - add variable **`SIGNPATH_ORGANIZATION_ID`** (your SignPath org id)

That's it — the release workflow (`.github/workflows/release.yml`) already has a
gated `SignPath/github-action-submit-signing-request@v2` step. It is a no-op until
`SIGNPATH_API_TOKEN` exists; once set, tagged releases sign the Windows `.exe`
automatically (build → upload artifact → submit for signing → attach the signed
binary). If the project/policy slugs differ from the defaults above, update them
in the workflow.

## Notes

- **macOS / Linux** binaries are not Authenticode-signed. macOS notarization would
  require an Apple Developer account; Linux needs no signing.
- The SignPath Foundation requires the download page to credit them — see the
  "Code signing" note in the README.
