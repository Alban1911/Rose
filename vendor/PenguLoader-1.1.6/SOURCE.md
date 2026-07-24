# Pengu Loader source

Rose compiles the loader executable from the vendored source during packaging.

Base implementation: https://github.com/PenguLoader/PenguLoader
Base version: v1.1.6 (4d641f5)

The vendored source retains Rose's branding and configuration integration.
Rose orchestrates the supported Pengu CLI from its Python integration layer;
the loader itself does not contain Rose-specific lifecycle commands.
