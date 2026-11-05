// Windows integration test: create a real suspended process with Explorer as
// its recorded parent, and verify that the launcher preserves its own token.
// Run once normally and once as administrator; no game or patcher is started.
#define wmain LtfLauncherMain
#include "../LeagueToolFlop-inj.cpp"
#undef wmain

struct RegistryValue {
    bool exists = false;
    DWORD type = REG_NONE;
    std::vector<BYTE> data;
    bool operator==(const RegistryValue&) const = default;
};

static RegistryValue ReadValue(HKEY key, const wchar_t* name)
{
    RegistryValue value;
    DWORD size = 0;
    LSTATUS status = RegQueryValueExW(key, name, NULL, &value.type, NULL, &size);
    if (status == ERROR_FILE_NOT_FOUND) return value;
    if (status != ERROR_SUCCESS) throw status;
    value.exists = true;
    value.data.resize(size);
    status = RegQueryValueExW(key, name, NULL, &value.type, value.data.data(), &size);
    if (status != ERROR_SUCCESS) throw status;
    return value;
}

static bool TestPolicyRestoration()
{
    wchar_t path[160];
    swprintf_s(path, L"Software\\Rose\\LauncherTests\\%lu-%llu",
        GetCurrentProcessId(), GetTickCount64());
    HKEY key = NULL;
    auto require = [](bool ok) { if (!ok) throw ERROR_INVALID_DATA; };
    bool ok = false;
    try {
        const wchar_t* app = L"ltk-manager.exe";
        const wchar_t* flags = L"--remote-debugging-port=12345";
        const wchar_t previous[] = L"--previous-argument=1";
        const BYTE binary[] = {1, 2, 3};
        for (int kind = 0; kind != 3; ++kind) {
            require(RegCreateKeyExW(HKEY_CURRENT_USER, path, 0, NULL, 0,
                KEY_READ | KEY_WRITE | KEY_WOW64_64KEY, NULL, &key, NULL) == ERROR_SUCCESS);
            RegDeleteValueW(key, app);
            if (kind == 1)
                require(RegSetValueExW(key, app, 0, REG_SZ, (const BYTE*)previous,
                    sizeof(previous)) == ERROR_SUCCESS);
            if (kind == 2)
                require(RegSetValueExW(key, app, 0, REG_BINARY, binary,
                    sizeof(binary)) == ERROR_SUCCESS);
            RegistryValue before = ReadValue(key, app);
            {
                ScopedCdpPolicy policy(HKEY_CURRENT_USER, path);
                require(policy.Install(L"C:\\test\\ltk-manager.exe", flags));
                RegistryValue installed = ReadValue(key, app);
                require(installed.exists && installed.type == REG_SZ);
                std::wstring args((const wchar_t*)installed.data.data());
                require(args.find(flags) != std::wstring::npos);
                if (kind == 1) require(args.find(previous) != std::wstring::npos);
                // An early return or failed spawn uses this same destructor.
            }
            require(ReadValue(key, app) == before);
            RegCloseKey(key);
            key = NULL;
            require(RegDeleteKeyExW(HKEY_CURRENT_USER, path, KEY_WOW64_64KEY, 0) == ERROR_SUCCESS);
        }

        // Another application can add a value after we created the shared key.
        {
            ScopedCdpPolicy policy(HKEY_CURRENT_USER, path);
            require(policy.Install(L"C:\\test\\ltk-manager.exe", flags));
            require(RegOpenKeyExW(HKEY_CURRENT_USER, path, 0,
                KEY_READ | KEY_WRITE | KEY_WOW64_64KEY, &key) == ERROR_SUCCESS);
            require(RegSetValueExW(key, L"other-app.exe", 0, REG_BINARY,
                binary, sizeof(binary)) == ERROR_SUCCESS);
        }
        require(!ReadValue(key, L"ltk-manager.exe").exists);
        require(ReadValue(key, L"other-app.exe").data == std::vector<BYTE>(binary, binary + sizeof(binary)));

        // A concurrent change to our value belongs to its writer, not us.
        {
            ScopedCdpPolicy policy(HKEY_CURRENT_USER, path);
            require(policy.Install(L"C:\\test\\ltk-manager.exe", flags));
            require(RegSetValueExW(key, app, 0, REG_SZ, (const BYTE*)previous,
                sizeof(previous)) == ERROR_SUCCESS);
        }
        require(ReadValue(key, app).data == std::vector<BYTE>((const BYTE*)previous,
            (const BYTE*)previous + sizeof(previous)));
        ok = true;
    }
    catch (LSTATUS error) {
        printf("{\"policy_restore_ok\":false,\"error\":%ld}\n", error);
    }
    catch (...) {
        printf("{\"policy_restore_ok\":false,\"error\":\"unexpected exception\"}\n");
    }
    if (key) RegCloseKey(key);
    RegDeleteKeyExW(HKEY_CURRENT_USER, path, KEY_WOW64_64KEY, 0);
    printf("{\"policy_restore_ok\":%s}\n", ok ? "true" : "false");
    return ok;
}

int wmain()
{
    if (!TestPolicyRestoration()) return 14;
    DWORD shellPid = ShellPid();
    // CI runners may have no desktop shell. The explicit parent/token path
    // still runs there, using this test process as the recorded parent.
    if (!shellPid) shellPid = GetCurrentProcessId();
    EnablePrivilege(L"SeDebugPrivilege");
    EnablePrivilege(L"SeIncreaseQuotaPrivilege");
    EnablePrivilege(L"SeAssignPrimaryTokenPrivilege");
    HANDLE shell = OpenProcess(PROCESS_CREATE_PROCESS, FALSE, shellPid);
    if (!shell) return 10;
    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    SIZE_T bytes = 0;
    InitializeProcThreadAttributeList(NULL, 1, 0, &bytes);
    startup.lpAttributeList = (LPPROC_THREAD_ATTRIBUTE_LIST)HeapAlloc(GetProcessHeap(), 0, bytes);
    if (!startup.lpAttributeList ||
        !InitializeProcThreadAttributeList(startup.lpAttributeList, 1, 0, &bytes) ||
        !UpdateProcThreadAttribute(startup.lpAttributeList, 0, PROC_THREAD_ATTRIBUTE_PARENT_PROCESS,
            &shell, sizeof(shell), NULL, NULL)) return 11;
    wchar_t child[MAX_PATH] = {};
    GetSystemDirectoryW(child, MAX_PATH);
    wcscat_s(child, L"\\cmd.exe");
    wchar_t command[MAX_PATH + 32] = {};
    swprintf_s(command, L"\"%s\" /d /c exit 0", child);
    PROCESS_INFORMATION process{};
    bool spawned = SpawnWithCurrentToken(child, command, NULL, &startup, true,
        CREATE_SUSPENDED | CREATE_NO_WINDOW, &process);
    DWORD error = spawned ? 0 : GetLastError();
    DeleteProcThreadAttributeList(startup.lpAttributeList);
    HeapFree(GetProcessHeap(), 0, startup.lpAttributeList);
    CloseHandle(shell);
    if (!spawned) {
        printf("{\"ok\":false,\"spawn_error\":%lu}\n", error);
        return 12;
    }
    DWORD callerIntegrity = IntegrityLevel(GetCurrentProcess());
    DWORD childIntegrity = IntegrityLevel(process.hProcess);
    DWORD parent = ParentPidOf(process.dwProcessId);
    bool ok = callerIntegrity != 0 && childIntegrity == callerIntegrity && parent == shellPid;
    printf("{\"ok\":%s,\"caller_integrity\":%lu,\"child_integrity\":%lu,"
        "\"shell_pid\":%lu,\"recorded_parent_pid\":%lu}\n",
        ok ? "true" : "false", callerIntegrity, childIntegrity, shellPid, parent);
    TerminateProcess(process.hProcess, 0);
    WaitForSingleObject(process.hProcess, 5000);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return ok ? 0 : 13;
}
