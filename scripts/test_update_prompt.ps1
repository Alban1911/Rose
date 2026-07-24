$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

try {
    $pythonCode = @'
from launcher.core.launcher import _confirm_update


class FakeDialog:
    hwnd = None

    def set_marquee(self, value):
        pass

    def set_detail(self, value):
        print(value)

    def set_status(self, value):
        print(value)

    def pump_messages(self):
        pass


print("Result:", _confirm_update(FakeDialog(), "9.9.9", "1.2.12"))
'@

    $pythonCode | python -
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
