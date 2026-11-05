#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <tlhelp32.h>
#include <userenv.h>
#include <stdio.h>
#include <stdarg.h>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "userenv.lib")
// made by lol123love
static const char* kLogPath = "C:\\Users\\Public\\ltk_launcher.log";

// Exit codes Rose reads (injection/overlay/overlay_manager.py)
enum LauncherExit {
    kExitOk = 0,
    kExitDllMissing = 1,
    kExitExeMissing = 2,
    kExitSpawnFailed = 3,
    kExitInjectFailed = 4,
    kExitAlreadyRunning = 5,
    kExitNoLiveInstance = 6,
};

static void LogTo(const char* path, const char* text, int length)
{
    HANDLE h = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
        OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return;
    SetFilePointer(h, 0, NULL, FILE_END);
    DWORD w = 0;
    WriteFile(h, text, (DWORD)length, &w, NULL);
    WriteFile(h, "\r\n", 2, &w, NULL);
    CloseHandle(h);
}

// The shared log lives in C:\Users\Public, which only an elevated launcher can
// write on some machines: a copy started with the user's token (and so the
// bridge's own helper) falls back to the user's temp folder
static const char* FallbackLogPath()
{
    static char path[MAX_PATH] = {};
    if (path[0]) return path;
    char temp[MAX_PATH] = {};
    if (GetTempPathA(MAX_PATH, temp) == 0) return kLogPath;
    _snprintf_s(path, sizeof(path), _TRUNCATE, "%sltk_launcher.log", temp);
    return path;
}

static void Log(const char* fmt, ...)
{
    char buf[1024];
    va_list ap; va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf) - 1, fmt, ap);
    va_end(ap);
    if (n <= 0) return;
    if (n >= (int)sizeof(buf) - 1) n = (int)sizeof(buf) - 2;

    HANDLE h = CreateFileA(kLogPath, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
        OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h != INVALID_HANDLE_VALUE) {
        SetFilePointer(h, 0, NULL, FILE_END);
        DWORD w = 0;
        WriteFile(h, buf, (DWORD)n, &w, NULL);
        WriteFile(h, "\r\n", 2, &w, NULL);
        CloseHandle(h);
        return;
    }
    LogTo(FallbackLogPath(), buf, n);
}

static bool IsLtkManagerExe(const wchar_t* name)
{
    return _wcsicmp(name, L"ltk-manager.exe") == 0 || _wcsicmp(name, L"LTK Manager.exe") == 0;
}

// Every running LTK Manager
static std::vector<DWORD> LtkManagerPids()
{
    std::vector<DWORD> pids;
    HANDLE hSnap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (hSnap == INVALID_HANDLE_VALUE) return pids;

    PROCESSENTRY32W pe{};
    pe.dwSize = sizeof(pe);
    if (Process32FirstW(hSnap, &pe)) {
        do {
            if (IsLtkManagerExe(pe.szExeFile)) pids.push_back(pe.th32ProcessID);
        } while (Process32NextW(hSnap, &pe));
    }
    CloseHandle(hSnap);
    return pids;
}

// An LTK Manager that was not running before the launch and is not the
// spawned process: the one the spawned process restarted itself as
static DWORD FindNewLtkPid(const std::vector<DWORD>& before, DWORD spawned)
{
    DWORD found = 0;
    for (DWORD pid : LtkManagerPids()) {
        if (pid == spawned) continue;
        bool existed = false;
        for (DWORD old : before) existed = existed || old == pid;
        if (!existed) found = pid;
    }
    return found;
}

// A free loopback port for WebView2's remote debugging endpoint (0 if none)
static int PickFreePort()
{
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return 0;
    int port = 0;
    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s != INVALID_SOCKET) {
        sockaddr_in a{}; a.sin_family = AF_INET; a.sin_port = 0;
        inet_pton(AF_INET, "127.0.0.1", &a.sin_addr);
        int len = sizeof(a);
        if (bind(s, (sockaddr*)&a, sizeof(a)) == 0 && getsockname(s, (sockaddr*)&a, &len) == 0)
            port = ntohs(a.sin_port);
        closesocket(s);
    }
    WSACleanup();
    return port;
}

// WebView2 150+ ignores WEBVIEW2_* environment overrides in an elevated
// application. Use its documented HKLM override for this executable only,
// restoring the prior value as soon as the browser has opened its endpoint.
class ScopedCdpPolicy {
    HKEY key_ = NULL;
    HKEY root_;
    const wchar_t* path_;
    std::wstring app_;
    DWORD oldType_ = REG_NONE;
    std::vector<BYTE> old_, installed_;
    bool existed_ = false, active_ = false;
    static constexpr const wchar_t* defaultPath_ =
        L"Software\\Policies\\Microsoft\\Edge\\WebView2\\AdditionalBrowserArguments";
public:
    explicit ScopedCdpPolicy(HKEY root = HKEY_LOCAL_MACHINE, const wchar_t* path = defaultPath_)
        : root_(root), path_(path) {}
    ScopedCdpPolicy(const ScopedCdpPolicy&) = delete;
    ScopedCdpPolicy& operator=(const ScopedCdpPolicy&) = delete;
    ~ScopedCdpPolicy() { Restore(); if (key_) RegCloseKey(key_); }

    bool Install(const wchar_t* exe, const wchar_t* arguments)
    {
        const wchar_t* base = wcsrchr(exe, L'\\');
        app_ = base ? base + 1 : exe;
        LSTATUS status = RegCreateKeyExW(root_, path_, 0, NULL, 0,
            KEY_QUERY_VALUE | KEY_SET_VALUE | KEY_WOW64_64KEY, NULL, &key_, NULL);
        if (status != ERROR_SUCCESS) { SetLastError(status); return false; }
        DWORD bytes = 0;
        status = RegQueryValueExW(key_, app_.c_str(), NULL, &oldType_, NULL, &bytes);
        if (status == ERROR_SUCCESS) {
            existed_ = true;
            old_.resize(bytes);
            status = RegQueryValueExW(key_, app_.c_str(), NULL, &oldType_, old_.data(), &bytes);
            if (status != ERROR_SUCCESS) { SetLastError(status); return false; }
            old_.resize(bytes);
        }
        else if (status != ERROR_FILE_NOT_FOUND) { SetLastError(status); return false; }
        std::wstring combined;
        if (existed_ && oldType_ == REG_SZ && old_.size() % sizeof(wchar_t) == 0) {
            for (size_t i = 0; i < old_.size() / sizeof(wchar_t); ++i) {
                wchar_t value;
                memcpy(&value, old_.data() + i * sizeof(value), sizeof(value));
                if (!value) break;
                combined.push_back(value);
            }
            if (!combined.empty()) combined += L" ";
        }
        combined += arguments;
        installed_.resize((combined.size() + 1) * sizeof(wchar_t));
        memcpy(installed_.data(), combined.c_str(), installed_.size());
        status = RegSetValueExW(key_, app_.c_str(), 0, REG_SZ, installed_.data(), (DWORD)installed_.size());
        if (status != ERROR_SUCCESS) { SetLastError(status); return false; }
        active_ = true;
        Log("[cdp] temporary WebView2 arguments set for %ls", app_.c_str());
        return true;
    }

    bool Restore()
    {
        if (!active_) return true;
        DWORD type = 0, bytes = 0;
        LSTATUS status = RegQueryValueExW(key_, app_.c_str(), NULL, &type, NULL, &bytes);
        std::vector<BYTE> current(bytes);
        if (status == ERROR_SUCCESS)
            status = RegQueryValueExW(key_, app_.c_str(), NULL, &type, current.data(), &bytes);
        if (status != ERROR_SUCCESS && status != ERROR_FILE_NOT_FOUND) {
            Log("[err] reading WebView2 arguments before restoration failed (err=%lu)", (DWORD)status);
            return false;
        }
        if (status == ERROR_FILE_NOT_FOUND || type != REG_SZ || current != installed_) {
            // Do not overwrite a policy somebody else changed while we launched.
            Log("[warn] WebView2 arguments changed externally; leaving the current value alone");
            active_ = false;
            return true;
        }
        status = existed_
            ? RegSetValueExW(key_, app_.c_str(), 0, oldType_, old_.data(), (DWORD)old_.size())
            : RegDeleteValueW(key_, app_.c_str());
        if (status != ERROR_SUCCESS) {
            Log("[err] restoring WebView2 arguments failed (err=%lu)", (DWORD)status);
            return false;
        }
        active_ = false;
        RegCloseKey(key_);
        key_ = NULL;
        // Leave the shared key itself alone: other apps may have added values.
        Log("[cdp] restored the previous WebView2 arguments for %ls", app_.c_str());
        return true;
    }
};

static bool WaitForCdp(int port, HANDLE manager)
{
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return false;
    ULONGLONG start = GetTickCount64();
    bool ready = false;
    while (GetTickCount64() - start < 30000 && WaitForSingleObject(manager, 0) == WAIT_TIMEOUT) {
        SOCKET socket_ = socket(AF_INET, SOCK_STREAM, 0);
        if (socket_ == INVALID_SOCKET) break;
        sockaddr_in address{};
        address.sin_family = AF_INET;
        address.sin_port = htons((u_short)port);
        inet_pton(AF_INET, "127.0.0.1", &address.sin_addr);
        if (connect(socket_, (sockaddr*)&address, sizeof(address)) == 0) {
            DWORD timeout = 1000;
            setsockopt(socket_, SOL_SOCKET, SO_RCVTIMEO, (char*)&timeout, sizeof(timeout));
            setsockopt(socket_, SOL_SOCKET, SO_SNDTIMEO, (char*)&timeout, sizeof(timeout));
            const char request[] = "GET /json/version HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
            send(socket_, request, sizeof(request) - 1, 0);
            char response[256] = {};
            int length = recv(socket_, response, sizeof(response) - 1, 0);
            ready = length > 0 && (strncmp(response, "HTTP/1.1 200", 12) == 0 ||
                                  strncmp(response, "HTTP/1.0 200", 12) == 0);
        }
        closesocket(socket_);
        if (ready) break;
        Sleep(100);
    }
    WSACleanup();
    return ready;
}

static bool IsElevated()
{
    HANDLE token = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) return false;
    TOKEN_ELEVATION elevation{};
    DWORD size = 0;
    bool elevated = GetTokenInformation(token, TokenElevation, &elevation, sizeof(elevation), &size)
        && elevation.TokenIsElevated;
    CloseHandle(token);
    return elevated;
}

// Read the actual integrity level, independently of LTK's elevation check.
// A successful hook installation alone does not prove the DLL can enter the game.
static DWORD IntegrityLevel(HANDLE process)
{
    HANDLE token = NULL;
    if (!OpenProcessToken(process, TOKEN_QUERY, &token)) return 0;
    DWORD bytes = 0;
    GetTokenInformation(token, TokenIntegrityLevel, NULL, 0, &bytes);
    std::vector<BYTE> data(bytes);
    DWORD level = 0;
    if (bytes && GetTokenInformation(token, TokenIntegrityLevel, data.data(), bytes, &bytes)) {
        PSID sid = ((TOKEN_MANDATORY_LABEL*)data.data())->Label.Sid;
        if (IsValidSid(sid)) {
            BYTE count = *GetSidSubAuthorityCount(sid);
            if (count) level = *GetSidSubAuthority(sid, count - 1);
        }
    }
    CloseHandle(token);
    return level;
}

// An explicit primary token is necessary here: CreateProcessW with an Explorer
// parent inherits Explorer's medium-integrity token, even from an elevated Rose.
static bool SpawnWithCurrentToken(const wchar_t* exePath, wchar_t* cmdLine,
                                 const wchar_t* workDir, STARTUPINFOEXW* six,
                                 bool shellParent, DWORD flags, PROCESS_INFORMATION* pi)
{
    HANDLE token = NULL;
    if (!OpenProcessToken(GetCurrentProcess(),
        TOKEN_QUERY | TOKEN_DUPLICATE | TOKEN_ASSIGN_PRIMARY, &token)) return false;
    six->StartupInfo.cb = shellParent ? sizeof(*six) : sizeof(STARTUPINFOW);
    BOOL ok = CreateProcessAsUserW(token, exePath, cmdLine, NULL, NULL, FALSE,
        flags | (shellParent ? EXTENDED_STARTUPINFO_PRESENT : 0), NULL,
        workDir, &six->StartupInfo, pi);
    DWORD error = ok ? ERROR_SUCCESS : GetLastError();
    CloseHandle(token);
    SetLastError(error);
    return ok != 0;
}

// The desktop user's unelevated token for the legacy --unelevated path.
static HANDLE ShellUserToken()
{
    // CreateProcessWithTokenW wants it (held, but off, in an elevated token)
    HANDLE self = NULL;
    if (OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES, &self)) {
        TOKEN_PRIVILEGES tp{};
        tp.PrivilegeCount = 1;
        if (LookupPrivilegeValueW(NULL, L"SeIncreaseQuotaPrivilege", &tp.Privileges[0].Luid)) {
            tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED;
            AdjustTokenPrivileges(self, FALSE, &tp, 0, NULL, NULL);
        }
        CloseHandle(self);
    }

    HWND shell = GetShellWindow();
    if (!shell) { Log("[warn] no shell window to take the desktop user's token from"); return NULL; }
    DWORD shellPid = 0;
    GetWindowThreadProcessId(shell, &shellPid);
    HANDLE proc = OpenProcess(PROCESS_QUERY_INFORMATION, FALSE, shellPid);
    if (!proc) { Log("[warn] OpenProcess(shell pid=%lu) err=%lu", shellPid, GetLastError()); return NULL; }
    HANDLE token = NULL, primary = NULL;
    if (OpenProcessToken(proc, TOKEN_DUPLICATE, &token)) {
        if (!DuplicateTokenEx(token,
            TOKEN_QUERY | TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE | TOKEN_ADJUST_DEFAULT | TOKEN_ADJUST_SESSIONID,
            NULL, SecurityImpersonation, TokenPrimary, &primary)) {
            Log("[warn] DuplicateTokenEx err=%lu", GetLastError());
            primary = NULL;
        }
        CloseHandle(token);
    }
    else {
        Log("[warn] OpenProcessToken(shell) err=%lu", GetLastError());
    }
    CloseHandle(proc);
    return primary;
}

// LTK Manager's patcher DLL verifies the chain of the process that started
// it: ltk_patcher_host.exe <- ltk-manager.exe <- explorer.exe, each image
// signed (docs/ltf-vrf-host-verification.md). A manager started from this
// launcher has ltk_launcher.exe there instead, so the DLL refuses the overlay
// with VRF0000000x. Seeding the new process's parent as the desktop shell keeps
// the env, the suspended start and the debug port while making that chain look
// like a hand-started manager's.
static bool EnablePrivilege(const wchar_t* name)
{
    HANDLE token = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &token)) return false;
    TOKEN_PRIVILEGES tp{};
    tp.PrivilegeCount = 1;
    bool ok = LookupPrivilegeValueW(NULL, name, &tp.Privileges[0].Luid)
        && AdjustTokenPrivileges(token, FALSE, &tp, 0, NULL, NULL)
        && GetLastError() == ERROR_SUCCESS;
    CloseHandle(token);
    return ok;
}

static bool IsExplorerExe(const wchar_t* name)
{
    return _wcsicmp(name, L"explorer.exe") == 0;
}

// The parent Windows records for *pid* (the chain the patcher's DLL reads)
static DWORD ParentPidOf(DWORD pid)
{
    DWORD parent = 0;
    HANDLE hSnap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (hSnap == INVALID_HANDLE_VALUE) return 0;
    PROCESSENTRY32W pe{};
    pe.dwSize = sizeof(pe);
    if (Process32FirstW(hSnap, &pe)) {
        do {
            if (pe.th32ProcessID == pid) {
                parent = pe.th32ParentProcessID;
                break;
            }
        } while (Process32NextW(hSnap, &pe));
    }
    CloseHandle(hSnap);
    return parent;
}

// Explorer in this session: the shell window's process, else any explorer.exe
// of the session (the shell window is missing while it restarts)
static DWORD ShellPid()
{
    DWORD pid = 0;
    HWND shell = GetShellWindow();
    if (shell) GetWindowThreadProcessId(shell, &pid);
    if (pid) return pid;

    DWORD session = 0;
    ProcessIdToSessionId(GetCurrentProcessId(), &session);
    HANDLE hSnap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (hSnap == INVALID_HANDLE_VALUE) return 0;
    PROCESSENTRY32W pe{};
    pe.dwSize = sizeof(pe);
    if (Process32FirstW(hSnap, &pe)) {
        do {
            if (!IsExplorerExe(pe.szExeFile)) continue;
            DWORD other = 0;
            if (ProcessIdToSessionId(pe.th32ProcessID, &other) && other == session) {
                pid = pe.th32ProcessID;
                break;
            }
        } while (Process32NextW(hSnap, &pe));
    }
    CloseHandle(hSnap);
    return pid;
}

using EnvVars = std::vector<std::pair<std::wstring, std::wstring>>;

// The environment *token*'s user logs in with, plus (over) *vars*
static std::wstring EnvironmentFor(HANDLE token, const EnvVars& vars)
{
    std::wstring block;
    LPVOID env = NULL;
    if (CreateEnvironmentBlock(&env, token, FALSE) && env) {
        for (const wchar_t* entry = (const wchar_t*)env; *entry; entry += wcslen(entry) + 1) {
            const wchar_t* eq = wcschr(entry + 1, L'=');  // "=C:=C:\" entries start with '='
            bool replaced = false;
            for (auto const& var : vars) {
                if (eq && (size_t)(eq - entry) == var.first.size() &&
                    _wcsnicmp(entry, var.first.c_str(), var.first.size()) == 0) replaced = true;
            }
            if (!replaced) { block += entry; block.push_back(L'\0'); }
        }
        DestroyEnvironmentBlock(env);
    }
    for (auto const& var : vars) {
        block += var.first + L"=" + var.second;
        block.push_back(L'\0');
    }
    block.push_back(L'\0');
    return block;
}

static bool ResolveDllPath(wchar_t* outPath, size_t outLen)
{
    outPath[0] = 0;
    DWORD n = GetModuleFileNameW(NULL, outPath, (DWORD)outLen);
    if (n == 0 || n >= outLen) { Log("[err] GetModuleFileNameW"); return false; }
    wchar_t* slash = wcsrchr(outPath, L'\\');
    if (!slash) { Log("[err] no backslash"); return false; }
    *(slash + 1) = 0;
    if (wcslen(outPath) + 32 >= outLen) { Log("[err] buffer small"); return false; }
    wcscat_s(outPath, outLen, L"LeagueToolFlop.dll");

    if (GetFileAttributesW(outPath) == INVALID_FILE_ATTRIBUTES) {
        Log("[err] LeagueToolFlop.dll not found: %ls", outPath);
        return false;
    }
    Log("[resolve] LeagueToolFlop.dll = %ls", outPath);
    return true;
}

static void ResolveDefaultExe(wchar_t* outPath, size_t outLen)
{
    outPath[0] = 0;
    const wchar_t* directDefaults[] = {
        L"C:\\Program Files\\LTK Manager\\ltk-manager.exe",
        L"C:\\Program Files\\LTK Manager\\LTK Manager.exe",
    };
    for (auto candidate : directDefaults) {
        if (GetFileAttributesW(candidate) != INVALID_FILE_ATTRIBUTES) {
            wcscpy_s(outPath, outLen, candidate);
            Log("[resolve] found default exe: %ls", outPath);
            return;
        }
    }
    outPath[0] = 0;
    Log("[resolve] no candidate found");
}

// LTK Manager has to run as the desktop user, but
// CreateProcessWithTokenW refuses EXTENDED_STARTUPINFO_PRESENT (err 87), so an
// elevated launcher cannot seed the shell parent itself. It starts a copy of
// this launcher with the desktop user's token instead: that copy opens
// explorer.exe without privilege trouble, seeds the parent and injects. The
// copy cannot inherit this process's stdout (CreateProcessWithTokenW does not
// inherit handles), hence the pid file.
static bool SpawnAsUserChild(HANDLE token, const std::wstring& env, const wchar_t* exePath,
                             bool noHide, DWORD* outPid)
{
    *outPid = 0;
    wchar_t self[MAX_PATH] = {};
    if (GetModuleFileNameW(NULL, self, MAX_PATH) == 0) return false;
    wchar_t tempDir[MAX_PATH] = {};
    if (GetTempPathW(MAX_PATH, tempDir) == 0) return false;
    wchar_t pidFile[MAX_PATH] = {};
    swprintf_s(pidFile, L"%sltk_launcher_%lu.pid", tempDir, GetCurrentProcessId());
    DeleteFileW(pidFile);

    wchar_t cmdLine[MAX_PATH * 2 + 512];
    swprintf_s(cmdLine, L"\"%s\" --as-user-child --quiet --exe \"%s\" --pid-file \"%s\"%s",
        self, exePath, pidFile, noHide ? L" --no-hide" : L"");

    STARTUPINFOW si{};
    si.cb = sizeof(si);
    if (!noHide) {
        si.dwFlags = STARTF_USESHOWWINDOW;
        si.wShowWindow = SW_HIDE;
    }
    PROCESS_INFORMATION pi{};
    if (!CreateProcessWithTokenW(token, 0, self, cmdLine, CREATE_UNICODE_ENVIRONMENT,
        (LPVOID)env.data(), NULL, &si, &pi)) {
        Log("[warn] helper spawn err=%lu", GetLastError());
        return false;
    }
    Log("[launch] helper started pid=%lu", pi.dwProcessId);

    bool ok = false;
    if (WaitForSingleObject(pi.hProcess, 45000) == WAIT_OBJECT_0) {
        DWORD code = 1;
        GetExitCodeProcess(pi.hProcess, &code);
        if (code == kExitOk) {
            HANDLE f = CreateFileW(pidFile, GENERIC_READ, FILE_SHARE_READ, NULL,
                OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
            if (f != INVALID_HANDLE_VALUE) {
                char text[32] = {};
                DWORD read = 0;
                if (ReadFile(f, text, sizeof(text) - 1, &read, NULL)) {
                    text[read] = 0;
                    *outPid = (DWORD)strtoul(text, NULL, 10);
                }
                CloseHandle(f);
            }
            ok = *outPid != 0;
        }
        else {
            Log("[warn] helper exited with code %lu", code);
        }
    }
    else {
        Log("[warn] helper did not finish in time");
    }
    DeleteFileW(pidFile);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return ok;
}

// CreateProcessWithTokenW refuses the extended startup info (err 87), but
// CreateProcessAsUser takes the same STARTUPINFOEX: with the desktop user's
// token it spawns the manager with the shell parent in one call
static bool SpawnWithUserToken(HANDLE token, const std::wstring& env, const wchar_t* exePath,
                               wchar_t* cmdLine, const wchar_t* workDir,
                               STARTUPINFOEXW* six, DWORD flags, PROCESS_INFORMATION* pi)
{
    EnablePrivilege(L"SeAssignPrimaryTokenPrivilege");
    EnablePrivilege(L"SeIncreaseQuotaPrivilege");
    six->StartupInfo.cb = sizeof(*six);
    return CreateProcessAsUserW(token, exePath, cmdLine, NULL, NULL, FALSE,
        flags | EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT,
        (LPVOID)env.data(), workDir, &six->StartupInfo, pi) != 0;
}

static bool InjectDll(DWORD pid, const wchar_t* dllPath)
{
    HANDLE hProc = OpenProcess(
        PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
        PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ,
        FALSE, pid);
    if (!hProc) { Log("[err] OpenProcess(pid=%lu) err=%lu", pid, GetLastError()); return false; }

    SIZE_T bytes = (wcslen(dllPath) + 1) * sizeof(wchar_t);
    LPVOID remote = VirtualAllocEx(hProc, NULL, bytes,
        MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!remote) {
        Log("[err] VirtualAllocEx err=%lu", GetLastError());
        CloseHandle(hProc); return false;
    }

    if (!WriteProcessMemory(hProc, remote, dllPath, bytes, NULL)) {
        Log("[err] WriteProcessMemory err=%lu", GetLastError());
        VirtualFreeEx(hProc, remote, 0, MEM_RELEASE); CloseHandle(hProc); return false;
    }

    FARPROC loadLib = GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "LoadLibraryW");
    if (!loadLib) {
        Log("[err] GetProcAddress");
        VirtualFreeEx(hProc, remote, 0, MEM_RELEASE); CloseHandle(hProc); return false;
    }

    HANDLE th = CreateRemoteThread(hProc, NULL, 0,
        (LPTHREAD_START_ROUTINE)loadLib, remote, 0, NULL);
    if (!th) {
        Log("[err] CreateRemoteThread err=%lu", GetLastError());
        VirtualFreeEx(hProc, remote, 0, MEM_RELEASE); CloseHandle(hProc); return false;
    }

    DWORD wait = WaitForSingleObject(th, 15000);
    DWORD exitCode = 0;
    if (wait != WAIT_TIMEOUT) {
        GetExitCodeThread(th, &exitCode);
        Log("[inject] LoadLibraryW(pid=%lu) -> 0x%lX", pid, exitCode);
    }
    else {
        Log("[warn] inject timed out");
        exitCode = 1;
    }

    CloseHandle(th);
    VirtualFreeEx(hProc, remote, 0, MEM_RELEASE);
    CloseHandle(hProc);
    return exitCode != 0;
}

static int Fail(bool quiet, int code, const wchar_t* message)
{
    Log("[err] %ls", message);
    if (!quiet) MessageBoxW(NULL, message, L"LTK Bridge Launcher", MB_ICONERROR);
    return code;
}

// wmain: the paths arrive as UTF-16, so a user or install folder with
// non-ASCII characters (C:\Users\Josué\...) survives
int wmain(int argc, wchar_t** argv)
{
    CreateDirectoryA("C:\\Users\\Public", NULL);
    Log("========== ltk_launcher ==========");

    wchar_t exePath[MAX_PATH] = {};
    wchar_t pidFile[MAX_PATH] = {};
    bool    noHide = false;
    // --quiet: no message boxes (Rose runs the launcher hidden, so a dialog
    // would block it until a timeout)
    bool    quiet = false;
    // Opt in to the original desktop-token path. By default an elevated Rose
    // keeps its own token so LTK can hook games in the same integrity context.
    bool    unelevated = false;
    // Internal: this copy was started with the desktop user's token by an
    // elevated launcher, which then reads the manager pid from --pid-file
    bool    asUserChild = false;

    for (int i = 1; i < argc; ++i) {
        if (!wcscmp(argv[i], L"--no-hide")) {
            noHide = true;
        }
        else if (!wcscmp(argv[i], L"--unelevated")) {
            unelevated = true;
        }
        else if (!wcscmp(argv[i], L"--as-user-child")) {
            asUserChild = true;
        }
        else if (!wcscmp(argv[i], L"--pid-file") && i + 1 < argc) {
            wcsncpy_s(pidFile, argv[++i], _TRUNCATE);
        }
        else if (!wcscmp(argv[i], L"--quiet")) {
            quiet = true;
        }
        else if (!wcscmp(argv[i], L"--exe") && i + 1 < argc) {
            wcsncpy_s(exePath, argv[++i], _TRUNCATE);
        }
        else if (argv[i][0] != L'-') {
            if (exePath[0] == 0)
                wcsncpy_s(exePath, argv[i], _TRUNCATE);
        }
    }

    if (exePath[0] == 0) ResolveDefaultExe(exePath, MAX_PATH);

    if (exePath[0] == 0 || GetFileAttributesW(exePath) == INVALID_FILE_ATTRIBUTES)
        return Fail(quiet, kExitExeMissing, L"ltk-manager.exe not found");

    wchar_t dllPath[MAX_PATH] = {};
    if (!ResolveDllPath(dllPath, MAX_PATH))
        return Fail(quiet, kExitDllMissing, L"LeagueToolFlop.dll must be in the same folder as ltk_launcher.exe.");

    // The bridge needs WebView2's debugging endpoint, which only an instance
    // started here has: a running LTK Manager belongs to the user and is left
    // alone (closing it could interrupt a library write)
    std::vector<DWORD> before = LtkManagerPids();
    if (!before.empty()) {
        Log("[err] LTK Manager is already running (pid=%lu)", before[0]);
        return Fail(quiet, kExitAlreadyRunning,
            L"LTK Manager is already open. Close it, then start it through this launcher.");
    }

    // A free port rather than the usual 9222: another program (a browser
    // being debugged, a stale WebView2) may hold that one. Only an Origin of
    // the endpoint itself is accepted, not every web page's
    int cdpPort = PickFreePort();
    if (cdpPort == 0) cdpPort = 9222;
    wchar_t browserArgs[256];
    swprintf_s(browserArgs, L"--remote-debugging-port=%d --remote-allow-origins=http://127.0.0.1:%d", cdpPort, cdpPort);
    wchar_t portText[16];
    swprintf_s(portText, L"%d", cdpPort);
    EnvVars vars = {
        { L"WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", browserArgs },
        { L"LTF_CDP_PORT", portText },
    };
    if (noHide) vars.push_back({ L"LTK_NO_HIDE", L"1" });
    for (auto const& var : vars) SetEnvironmentVariableW(var.first.c_str(), var.second.c_str());
    Log("[cdp] remote debugging on 127.0.0.1:%d", cdpPort);

    STARTUPINFOEXW six{};
    six.StartupInfo.cb = sizeof(STARTUPINFOW);
    if (!noHide) {
        six.StartupInfo.dwFlags = STARTF_USESHOWWINDOW;
        six.StartupInfo.wShowWindow = SW_HIDE;
    }
    PROCESS_INFORMATION pi{};

    wchar_t workDir[MAX_PATH] = {};
    wcscpy_s(workDir, exePath);
    if (wchar_t* slash = wcsrchr(workDir, L'\\')) *slash = 0;

    DWORD flags = CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP;

    // The parent the patcher DLL expects above LTK Manager
    DWORD shellPid = ShellPid();
    HANDLE shellProc = NULL;
    if (shellPid) {
        EnablePrivilege(L"SeDebugPrivilege");
        shellProc = OpenProcess(PROCESS_CREATE_PROCESS | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, shellPid);
    }
    bool shellParent = false;
    if (shellProc) {
        SIZE_T attrBytes = 0;
        InitializeProcThreadAttributeList(NULL, 1, 0, &attrBytes);
        six.lpAttributeList = (LPPROC_THREAD_ATTRIBUTE_LIST)HeapAlloc(GetProcessHeap(), 0, attrBytes);
        if (six.lpAttributeList
            && InitializeProcThreadAttributeList(six.lpAttributeList, 1, 0, &attrBytes)
            && UpdateProcThreadAttribute(six.lpAttributeList, 0, PROC_THREAD_ATTRIBUTE_PARENT_PROCESS,
                &shellProc, sizeof(shellProc), NULL, NULL)) {
            shellParent = true;
            Log("[launch] explorer.exe (pid=%lu) as the parent", shellPid);
        }
        else {
            Log("[warn] could not set the parent process (err=%lu)", GetLastError());
            if (six.lpAttributeList) {
                DeleteProcThreadAttributeList(six.lpAttributeList);
                HeapFree(GetProcessHeap(), 0, six.lpAttributeList);
                six.lpAttributeList = NULL;
            }
        }
    }
    else {
        Log("[warn] no explorer.exe (pid=%lu) to parent LTK Manager to", shellPid);
    }

    // Keep LTK from relaunching through the shell and losing the bridge's
    // environment. The process remains suspended until the bridge is injected.
    wchar_t cmdLine[MAX_PATH + 256];
    swprintf_s(cmdLine, L"\"%s\" --shell-relaunched", exePath);
    bool started = false;
    bool restartExpected = false;
    // One spawn attempt: the shell parent is dropped if the system refuses it
    // (CreateProcessWithTokenW does not document EXTENDED_STARTUPINFO_PRESENT)
    auto spawn = [&](HANDLE token, const std::wstring* env, bool withShellParent) -> bool {
        ZeroMemory(&pi, sizeof(pi));
        DWORD f = withShellParent ? (flags | EXTENDED_STARTUPINFO_PRESENT) : flags;
        six.StartupInfo.cb = withShellParent ? (DWORD)sizeof(six) : (DWORD)sizeof(STARTUPINFOW);
        BOOL ok = token
            ? CreateProcessWithTokenW(token, 0, exePath, cmdLine,
                f | CREATE_UNICODE_ENVIRONMENT, (LPVOID)env->data(),
                workDir[0] ? workDir : NULL, &six.StartupInfo, &pi)
            : CreateProcessW(exePath, cmdLine, NULL, NULL, FALSE, f, NULL,
                workDir[0] ? workDir : NULL, &six.StartupInfo, &pi);
        if (!ok && withShellParent) {
            Log("[warn] spawn with explorer.exe as the parent failed (err=%lu) - starting it as a child", GetLastError());
            six.StartupInfo.cb = sizeof(STARTUPINFOW);
            ok = token
                ? CreateProcessWithTokenW(token, 0, exePath, cmdLine,
                    flags | CREATE_UNICODE_ENVIRONMENT, (LPVOID)env->data(),
                    workDir[0] ? workDir : NULL, &six.StartupInfo, &pi)
                : CreateProcessW(exePath, cmdLine, NULL, NULL, FALSE, flags, NULL,
                    workDir[0] ? workDir : NULL, &six.StartupInfo, &pi);
        }
        return ok != 0;
    };

    DWORD helperPid = 0;
    bool preserveElevation = IsElevated() && !unelevated;
    ScopedCdpPolicy cdpPolicy;
    DWORD launcherIntegrity = IntegrityLevel(GetCurrentProcess());
    Log("[security] launcher integrity=%lu, preserve elevation=%s", launcherIntegrity,
        preserveElevation ? "yes" : "no");
    if (preserveElevation) {
        if (launcherIntegrity == 0)
            return Fail(quiet, kExitSpawnFailed, L"Could not read Rose's administrator integrity level.");
        if (!cdpPolicy.Install(exePath, browserArgs)) {
            Log("[err] could not configure elevated WebView2 (err=%lu)", GetLastError());
            return Fail(quiet, kExitSpawnFailed,
                L"Could not configure WebView2 for the administrator LTK session. See ltk_launcher.log.");
        }
        EnablePrivilege(L"SeIncreaseQuotaPrivilege");
        EnablePrivilege(L"SeAssignPrimaryTokenPrivilege");
        started = SpawnWithCurrentToken(exePath, cmdLine, workDir[0] ? workDir : NULL,
            &six, shellParent, flags, &pi);
        if (!started) {
            DWORD error = GetLastError();
            if (six.lpAttributeList) {
                DeleteProcThreadAttributeList(six.lpAttributeList);
                HeapFree(GetProcessHeap(), 0, six.lpAttributeList);
            }
            if (shellProc) CloseHandle(shellProc);
            Log("[err] could not preserve the administrator token (err=%lu)", error);
            return Fail(quiet, kExitSpawnFailed,
                L"Could not start LTK Manager with Rose's administrator token. See ltk_launcher.log.");
        }
        Log("[launch] started with the launcher's administrator token");
    }
    else if (IsElevated()) {
        HANDLE token = ShellUserToken();
        if (token) {
            std::wstring env = EnvironmentFor(token, vars);
            // The extended startup info (shell parent) is refused with a token
            // (err 87), so an unelevated copy of this launcher does the spawn
            bool oneCall = false;
            if (shellParent) {
                oneCall = SpawnWithUserToken(token, env, exePath, cmdLine, workDir[0] ? workDir : NULL,
                    &six, flags, &pi);
                if (!oneCall) Log("[warn] CreateProcessAsUser err=%lu", GetLastError());
            }
            if (oneCall) {
                started = true;
                Log("[launch] started unelevated as the desktop user, shell parent in one call");
            }
            else if (shellParent && SpawnAsUserChild(token, env, exePath, noHide, &helperPid)) {
                started = true;
                Log("[launch] started unelevated as the desktop user, shell parent by the helper");
            }
            else if (spawn(token, &env, shellParent)) {
                started = true;
                Log("[launch] started unelevated as the desktop user");
            }
            else {
                Log("[warn] CreateProcessWithTokenW err=%lu", GetLastError());
            }
            CloseHandle(token);
        }
        if (!started) {
            // LTK Manager restarts itself unelevated: the bridge then only
            // works if it is injected before WebView2 starts
            Log("[warn] starting LTK Manager elevated: it restarts itself through the shell");
            swprintf_s(cmdLine, L"\"%s\"", exePath);
            restartExpected = true;
        }
    }
    if (helperPid) {
        // The helper spawned, injected and resumed LTK Manager; it could not
        // inherit this process's stdout, so it left the pid behind
        if (six.lpAttributeList) {
            DeleteProcThreadAttributeList(six.lpAttributeList);
            HeapFree(GetProcessHeap(), 0, six.lpAttributeList);
            six.lpAttributeList = NULL;
        }
        if (shellProc) CloseHandle(shellProc);
        Log("[launch] helper reported pid=%lu", helperPid);
        printf("LTK_MANAGER_PID=%lu\n", helperPid);
        fflush(stdout);
        Log("========== launcher exiting ==========");
        return kExitOk;
    }
    if (!started && !spawn(NULL, NULL, shellParent)) {
        Log("[err] CreateProcessW err=%lu", GetLastError());
        return kExitSpawnFailed;
    }
    if (six.lpAttributeList) {
        DeleteProcThreadAttributeList(six.lpAttributeList);
        HeapFree(GetProcessHeap(), 0, six.lpAttributeList);
        six.lpAttributeList = NULL;
    }
    if (shellProc) CloseHandle(shellProc);
    DWORD managerIntegrity = IntegrityLevel(pi.hProcess);
    Log("[security] manager pid=%lu integrity=%lu", pi.dwProcessId, managerIntegrity);
    if (preserveElevation && (managerIntegrity == 0 || managerIntegrity < launcherIntegrity)) {
        Log("[err] manager lost the launcher's integrity level - terminating the spawned instance");
        TerminateProcess(pi.hProcess, kExitSpawnFailed);
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
        return Fail(quiet, kExitSpawnFailed, L"LTK Manager did not keep Rose's administrator permissions.");
    }
    DWORD parentPid = ParentPidOf(pi.dwProcessId);
    Log("[launch] spawned pid = %lu (suspended), parent pid = %lu (%s)", pi.dwProcessId, parentPid,
        !shellParent ? "no shell parent" : (parentPid == shellPid ? "explorer.exe" : "not explorer.exe"));

    if (!InjectDll(pi.dwProcessId, dllPath)) {
        Log("[err] injection failed - terminating ltk-manager.exe");
        TerminateProcess(pi.hProcess, 1);
        CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
        return kExitInjectFailed;
    }

    ResumeThread(pi.hThread);

    if (preserveElevation) {
        bool ready = WaitForCdp(cdpPort, pi.hProcess);
        bool restored = cdpPolicy.Restore();
        if (!ready || !restored) {
            Log("[err] elevated WebView2 endpoint ready=%s, policy restored=%s",
                ready ? "yes" : "no", restored ? "yes" : "no");
            TerminateProcess(pi.hProcess, kExitSpawnFailed);
            CloseHandle(pi.hThread);
            CloseHandle(pi.hProcess);
            return Fail(quiet, kExitSpawnFailed,
                L"The administrator LTK session did not finish initializing WebView2. See ltk_launcher.log.");
        }
        Log("[cdp] administrator WebView2 endpoint is ready on 127.0.0.1:%d", cdpPort);
    }

    // A restart through the shell shows as the spawned process exiting and
    // a new one taking over: the bridge then goes into that one. Without a
    // restart, the spawned process is the live one (a restart shows within
    // half a second; a slow PC gets several when one is expected).
    DWORD livePid = 0;
    bool spawnedExited = false;
    ULONGLONG settle = restartExpected ? 3000 : 800;
    ULONGLONG start = GetTickCount64();
    while (GetTickCount64() - start < 6000) {
        spawnedExited = WaitForSingleObject(pi.hProcess, 0) == WAIT_OBJECT_0;
        DWORD fresh = FindNewLtkPid(before, pi.dwProcessId);
        if (fresh) { livePid = fresh; break; }
        if (!spawnedExited && GetTickCount64() - start >= settle) { livePid = pi.dwProcessId; break; }
        Sleep(100);
    }
    if (livePid == 0 && !spawnedExited) livePid = pi.dwProcessId;

    if (spawnedExited || livePid != pi.dwProcessId) {
        DWORD procExit = 0;
        GetExitCodeProcess(pi.hProcess, &procExit);
        Log("[launch] spawned pid=%lu handed over (exit code %lu)", pi.dwProcessId, procExit);
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);

    if (livePid == 0) {
        Log("[err] the spawned LTK Manager exited and no new instance came up");
        return kExitNoLiveInstance;
    }
    if (livePid != pi.dwProcessId) {
        // A relaunch must not silently undo the permissions we preserved above.
        HANDLE live = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, livePid);
        DWORD liveIntegrity = live ? IntegrityLevel(live) : 0;
        if (live) CloseHandle(live);
        Log("[security] relaunched manager pid=%lu integrity=%lu", livePid, liveIntegrity);
        if (preserveElevation && liveIntegrity < launcherIntegrity)
            return Fail(quiet, kExitNoLiveInstance,
                L"LTK Manager restarted without Rose's administrator permissions. See ltk_launcher.log.");
        Log("[re-inject] injecting into live ltk-manager.exe pid=%lu", livePid);
        if (!InjectDll(livePid, dllPath)) return kExitInjectFailed;
    }
    else {
        Log("[launch] pid=%lu is alive and running!", livePid);
    }

    // Rose waits for the bridge of this process, not just any
    if (!asUserChild) {
        printf("LTK_MANAGER_PID=%lu\n", livePid);
        fflush(stdout);
    }
    if (pidFile[0]) {
        char text[32] = {};
        int n = _snprintf_s(text, sizeof(text), _TRUNCATE, "%lu", livePid);
        HANDLE f = CreateFileW(pidFile, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
            FILE_ATTRIBUTE_NORMAL, NULL);
        if (f != INVALID_HANDLE_VALUE) {
            DWORD written = 0;
            if (n > 0) WriteFile(f, text, (DWORD)n, &written, NULL);
            CloseHandle(f);
        }
        else {
            Log("[warn] could not write %ls (err=%lu)", pidFile, GetLastError());
        }
    }

    Log("========== launcher exiting ==========");
    return kExitOk;
}
