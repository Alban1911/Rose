# Pengu Loader source

Rose compiles the loader executable from the vendored source during packaging.

Base implementation: https://github.com/PenguLoader/PenguLoader
Base version: v1.1.6 (4d641f5)

The vendored source retains Rose's branding, configuration integration, and
command-line additions. Rose-managed mode uses Pengu's original IFEO activation
path and adds --rose-managed / --rose-stop only for Rose lifecycle control.