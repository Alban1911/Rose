# Experimental CN 16.20 section-selector patch

This is a **reproducible, opt-in binary patch builder**, not an official LTK
release or a general CN compatibility guarantee. It does not install or inject
anything. Rose's default loading path is not changed by this contribution.
No original or modified LTK binary is included in this directory.

## Problem and bounded change

With Rose 1.4.7, LTK 1.27.2 and CN/WeGame game build **16.20.824.8524**, the
original DLL attached but logged `.rdata section not found` followed by
`failed to install integrity hook`. The game uses `.ace` section names.

Replace only the 164-byte selector block at DLL RVA `[0x14bb1, 0x14c55)`.
Keep the existing `.rdata` case. Accept the additional `.ace` case only for the
observed PE timestamp, section count, image size, section RVA, virtual size and
characteristics. The builder also requires exact SHA-256 identities for both
the original DLL and game image. The original pattern search, hook logic,
expiry and verification flags are unchanged. There is no protection bypass,
memory-access retry, auto-deployment or automatic future-build fallback here.

| Input | SHA-256 |
| --- | --- |
| Original LTK DLL | `6d419057e6667994ba752ad0fb089b363db98267618644d7f7b6632441a21d74` |
| CN game image | `ee3c887b4579aeab12ca77b2a43cc1cc3411a8aa30bc43d2dfea856f6ce497c8` |

## Reproduce and test

Use a separate Python environment and install `requirements.txt` in this
directory. Supply your own legitimately obtained input files:

```powershell
python -m pip install -r native/cn_section_selector/requirements.txt
python -m unittest discover -s native/cn_section_selector -p "test_*.py"
python native/cn_section_selector/build_candidate.py --dll ORIGINAL.dll --game GAME.exe --output cn-selector-unsigned.dll
```

Output must be a new file. Input binaries are never written. Unsupported inputs
are rejected rather than patched approximately. A locally changed game or a
future DLL requires renewed analysis; do not relax the hash checks.

The synthetic selector tests check acceptance/rejection, control-flow exits,
nonvolatile registers, stack and memory preservation. They do not execute a
game, load a DLL, prove anti-cheat acceptance or establish long-term safety.

## Runtime evidence and limits

On 2026-10-13, the local user confirmed a selected Jinx skin became visible in
a CN training session. The same session logged `installed ossl integrity hook`,
`init done`, and redirects for `Global.zh_CN.wad.client` and `Jinx.wad.client`.
The game remained running after confirmation. This is not evidence for other
game builds, all skins, competitive play or account safety.

That private test used a candidate with SHA-256
`d1bf38ee3f0e58ed496613b098ed12038c199d3e337695b985533abff4fe46d9`, whose original
publisher signature was invalidated by modification. **That binary is not
redistributed.** This builder removes the certificate and recalculates the PE
checksum for distribution, preserving all section contents. The resulting
unsigned artifact has **not** separately been tested in game. Prefer a native
source fix and an appropriately signed build from the loader's maintainers.

## Attribution and distribution

LTK patcher binaries belong to League Toolkit and are covered by its
[LTK Patcher License](https://github.com/LeagueToolkit/ltk-manager/blob/v1.27.2/LTK-PATCHER-LICENSE.md).
Modified or separately redistributed binaries must not carry League Toolkit's
signature. The builder strips it; sign only with your own certificate if you
choose to sign. This work is not endorsed by League Toolkit. Do not disable
signature enforcement or anti-cheat protection to load its output.
