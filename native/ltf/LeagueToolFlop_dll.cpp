#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <bcrypt.h>
#include <psapi.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <wchar.h>
#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>
#include <utility>
#include <cstring>

#pragma comment(lib, "psapi.lib")
#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "bcrypt.lib")

namespace fs = std::filesystem;

static const char* kCredit = "made by lol123love for educational purposes and bcz love loves LTK :p BIG FLOP!";

// The log: in the folder the launcher names (LTF_LOG_DIR, Rose's logs\ltk
// folder), else in C:\Users\Public
static wchar_t g_apiLog[MAX_PATH * 2] = L"C:\\Users\\Public\\ltk_api.log";
static const int   kApiPortStart = 46321;
static const int   kApiPortEnd = 46340;
static const DWORD kSocketTimeoutHttp = 3000;
static const DWORD kSocketTimeoutWs = 10000;
static const DWORD kCdpEvalBudgetMs = 15000;
// Installing a large mod (a map, a voiceover) takes LTK Manager well over
// the usual budget; giving up early would leave it installed untracked
static const DWORD kCdpInstallBudgetMs = 180000;

static HANDLE  g_hStopEvt = nullptr;
static int     g_apiPort = 0;
// WebView2's remote debugging port: the launcher's (LTF_CDP_PORT), else the
// one WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS names, else one picked here
static int     g_cdpPort = 9222;
// Every command but hello/ping must carry it: the API port also takes lines
// a web page POSTs to it. Published only where the user's processes read it.
static char    g_apiToken[33] = {};
static CRITICAL_SECTION g_cdpLock;
static volatile LONG    g_dllAttached = 0;

// Paths travel as UTF-8 in the JSON API; the file APIs need UTF-16 so that
// a non-ASCII user or game folder survives (the ANSI ones mangle it)
static std::wstring Utf8ToWide(const std::string& s) {
    if (s.empty()) return {};
    int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), nullptr, 0);
    if (n <= 0) return {};
    std::wstring w((size_t)n, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), w.data(), n);
    return w;
}
static std::string WideToUtf8(const std::wstring& w) {
    if (w.empty()) return {};
    int n = WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(), nullptr, 0, nullptr, nullptr);
    if (n <= 0) return {};
    std::string s((size_t)n, '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(), s.data(), n, nullptr, nullptr);
    return s;
}
static fs::path PathFromUtf8(const std::string& s) { return fs::path(Utf8ToWide(s)); }
static std::string PathToUtf8(const fs::path& p) { return WideToUtf8(p.wstring()); }

static const char* kLibGetInstalledMods = "plugin:library|get_installed_mods";
static const char* kLibToggleMod = "plugin:library|toggle_mod";
static const char* kLibUninstallMod = "plugin:library|uninstall_mod";
static const char* kLibInstallMod = "plugin:library|install_mod";
static const char* kLibHealthVerdicts = "plugin:library|get_mod_health_verdicts";
static const char* kPatStartPatcher = "plugin:patcher|start_patcher";
static const char* kPatStopPatcher = "plugin:patcher|stop_patcher";
static const char* kPatGetPatcherStatus = "plugin:patcher|get_patcher_status";

static void LogTo(const wchar_t* path, const char* fmt, va_list ap) {
    char buf[2048];
    int n = vsnprintf(buf, sizeof(buf) - 1, fmt, ap);
    if (n <= 0) return;
    if (n >= (int)sizeof(buf) - 1) n = (int)sizeof(buf) - 2;
    HANDLE h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ, NULL,
        OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return;
    SetFilePointer(h, 0, NULL, FILE_END);
    DWORD w = 0;
    WriteFile(h, buf, (DWORD)n, &w, NULL);
    WriteFile(h, "\r\n", 2, &w, NULL);
    CloseHandle(h);
}
static void ApiLog(const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    LogTo(g_apiLog, fmt, ap);
    va_end(ap);
}
static void LogInit(const wchar_t* path) {
    HANDLE h = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL,
        CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h != INVALID_HANDLE_VALUE) CloseHandle(h);
}
static void ResolveApiLog() {
    wchar_t dir[MAX_PATH] = {};
    DWORD n = GetEnvironmentVariableW(L"LTF_LOG_DIR", dir, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return;
    CreateDirectoryW(dir, NULL);
    swprintf_s(g_apiLog, L"%s\\ltk_api.log", dir);
}

static int ParseDebugPort(const wchar_t* args) {
    const wchar_t* key = L"--remote-debugging-port=";
    const wchar_t* p = wcsstr(args, key);
    if (!p) return 0;
    int port = _wtoi(p + wcslen(key));
    return (port > 0 && port < 65536) ? port : 0;
}

static void SetupCdpPort() {
    wchar_t buf[1024] = {};
    DWORD n = GetEnvironmentVariableW(L"LTF_CDP_PORT", buf, 1024);
    if (n > 0 && n < 1024) {
        int port = _wtoi(buf);
        if (port > 0 && port < 65536) { g_cdpPort = port; return; }
    }
    buf[0] = 0;
    n = GetEnvironmentVariableW(L"WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", buf, 1024);
    bool haveArgs = n > 0 && n < 1024;
    if (haveArgs) {
        int port = ParseDebugPort(buf);
        if (port) { g_cdpPort = port; return; }
    }
    // Below the dynamic range and away from the API ports
    int port = 20000 + (int)(((unsigned)rand() * 7919u + (unsigned)GetTickCount64()) % 20000u);
    wchar_t own[160];
    swprintf_s(own, L"--remote-debugging-port=%d --remote-allow-origins=http://127.0.0.1:%d", port, port);
    std::wstring args = haveArgs ? std::wstring(buf) + L" " + own : std::wstring(own);
    SetEnvironmentVariableW(L"WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", args.c_str());
    g_cdpPort = port;
}

static void SetSocketTimeout(SOCKET s, DWORD ms) {
    DWORD tv = ms;
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (char*)&tv, sizeof(tv));
    setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, (char*)&tv, sizeof(tv));
}

namespace mj {
    struct JVal {
        enum T { NUL, BOOL, NUM, STR, ARR, OBJ } t = NUL;
        bool b = false; double n = 0; std::string s;
        std::vector<JVal> arr;
        std::vector<std::pair<std::string, JVal>> obj;

        static JVal obj_() { JVal v; v.t = OBJ; return v; }
        static JVal arr_() { JVal v; v.t = ARR; return v; }
        static JVal str(const std::string& x) { JVal v; v.t = STR; v.s = x; return v; }
        static JVal num(double x) { JVal v; v.t = NUM; v.n = x; return v; }
        static JVal boo(bool x) { JVal v; v.t = BOOL; v.b = x; return v; }
        static JVal nul() { return JVal{}; }

        void set(const std::string& k, JVal v) {
            if (t != OBJ) { t = OBJ; obj.clear(); }
            for (auto& kv : obj) if (kv.first == k) { kv.second = std::move(v); return; }
            obj.emplace_back(k, std::move(v));
        }
        void push(JVal v) { if (t != ARR) { t = ARR; arr.clear(); } arr.push_back(std::move(v)); }
        const JVal* get(const std::string& k) const {
            if (t != OBJ) return nullptr;
            for (auto& kv : obj) if (kv.first == k) return &kv.second;
            return nullptr;
        }
        std::string asStr(const std::string& d = "") const { return t == STR ? s : d; }
        int64_t     asInt(int64_t d = 0) const { return t == NUM ? (int64_t)n : d; }
        bool        asBool(bool d = false) const { return t == BOOL ? b : d; }

        std::string dump() const { std::string o; ser(o); return o; }
        void ser(std::string& o) const {
            switch (t) {
            case NUL:  o += "null"; break;
            case BOOL: o += b ? "true" : "false"; break;
            case NUM: {
                char bb[40];
                if (n == (double)(int64_t)n) snprintf(bb, sizeof(bb), "%lld", (long long)n);
                else snprintf(bb, sizeof(bb), "%g", n);
                o += bb; break;
            }
            case STR: esc(o, s); break;
            case ARR: { o += '['; for (size_t i = 0; i < arr.size(); ++i) { if (i)o += ','; arr[i].ser(o); } o += ']'; break; }
            case OBJ: { o += '{'; for (size_t i = 0; i < obj.size(); ++i) { if (i)o += ','; esc(o, obj[i].first); o += ':'; obj[i].second.ser(o); } o += '}'; break; }
            }
        }
        static void esc(std::string& o, const std::string& s) {
            o += '"';
            for (char c : s) {
                switch (c) {
                case '"': o += "\\\""; break; case '\\': o += "\\\\"; break;
                case '\n': o += "\\n"; break;  case '\r': o += "\\r"; break;
                case '\t': o += "\\t"; break;
                default: if ((unsigned char)c < 0x20) { char b[8]; snprintf(b, sizeof(b), "\\u%04x", c); o += b; }
                       else o += c;
                }
            }
            o += '"';
        }
    };
    struct Parser {
        const char* p; const char* e; bool err = false;
        int depth = 0;
        void ws() { while (p < e && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) ++p; }
        bool eat(char c) { ws(); if (p < e && *p == c) { ++p; return true; } return false; }
        JVal parse() { return val(); }
        JVal val() {
            if (++depth > 200) { err = true; return {}; }
            ws(); if (p >= e) { err = true; depth--; return {}; }
            JVal res;
            if (*p == '{') res = ob();
            else if (*p == '[') res = ar();
            else if (*p == '"') res = JVal::str(str());
            else if (e - p >= 4 && !strncmp(p, "true", 4)) { p += 4; res = JVal::boo(true); }
            else if (e - p >= 5 && !strncmp(p, "false", 5)) { p += 5; res = JVal::boo(false); }
            else if (e - p >= 4 && !strncmp(p, "null", 4)) { p += 4; res = JVal::nul(); }
            else res = num();
            depth--;
            return res;
        }
        JVal ob() {
            JVal v = JVal::obj_(); ++p; ws();
            if (p < e && *p == '}') { ++p; return v; }
            while (p < e) {
                ws(); if (*p != '"') { err = true; return v; }
                std::string k = str(); ws();
                if (!eat(':')) { err = true; return v; }
                v.set(k, val()); ws();
                if (p < e && *p == ',') { ++p; continue; }
                if (p < e && *p == '}') { ++p; return v; }
                err = true; return v;
            }
            err = true; return v;
        }
        JVal ar() {
            JVal v = JVal::arr_(); ++p; ws();
            if (p < e && *p == ']') { ++p; return v; }
            while (p < e) {
                v.push(val()); ws();
                if (p < e && *p == ',') { ++p; continue; }
                if (p < e && *p == ']') { ++p; return v; }
                err = true; return v;
            }
            err = true; return v;
        }
        std::string str() {
            std::string o; if (p >= e || *p != '"') { err = true; return o; } ++p;
            while (p < e && *p != '"') {
                char c = *p++;
                if (c == '\\' && p < e) {
                    char x = *p++;
                    switch (x) {
                    case '"': o += '"'; break; case '\\': o += '\\'; break; case '/': o += '/'; break;
                    case 'n': o += '\n'; break; case 'r': o += '\r'; break; case 't': o += '\t'; break;
                    case 'b': o += '\b'; break; case 'f': o += '\f'; break;
                    case 'u': {
                        if (p + 4 > e) { err = true; return o; } unsigned c2 = 0;
                        for (int i = 0; i < 4; ++i) { char h = *p++; c2 = c2 * 16 + (h >= 'a' ? h - 'a' + 10 : h >= 'A' ? h - 'A' + 10 : h - '0'); }
                        if (c2 < 0x80) o += (char)c2;
                        else if (c2 < 0x800) { o += (char)(0xC0 | (c2 >> 6)); o += (char)(0x80 | (c2 & 0x3F)); }
                        else { o += (char)(0xE0 | (c2 >> 12)); o += (char)(0x80 | ((c2 >> 6) & 0x3F)); o += (char)(0x80 | (c2 & 0x3F)); }
                        break;
                    }
                    default: err = true; return o;
                    }
                }
                else o += c;
            }
            if (p >= e || *p != '"') { err = true; return o; }
            ++p; return o;
        }
        JVal num() {
            const char* s = p;
            if (p < e && *p == '-') ++p;
            while (p < e && ((*p >= '0' && *p <= '9') || *p == '.' || *p == 'e' || *p == 'E' || *p == '+' || *p == '-')) ++p;
            if (p == s) { err = true; return {}; }
            JVal v; v.t = JVal::NUM; v.n = atof(std::string(s, p - s).c_str()); return v;
        }
    };
    static JVal parse(const std::string& s) { Parser pp{ s.data(), s.data() + s.size() }; return pp.parse(); }
}

static std::string B64Enc(const uint8_t* d, size_t n) {
    static const char* T = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string o; o.reserve(((n + 2) / 3) * 4);
    for (size_t i = 0; i < n; i += 3) {
        uint32_t v = d[i] << 16;
        if (i + 1 < n) v |= d[i + 1] << 8;
        if (i + 2 < n) v |= d[i + 2];
        o += T[(v >> 18) & 63]; o += T[(v >> 12) & 63];
        o += (i + 1 < n) ? T[(v >> 6) & 63] : '=';
        o += (i + 2 < n) ? T[v & 63] : '=';
    }
    return o;
}

static std::vector<char> B64Dec(const std::string& in) {
    static const int T[256] = {
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,62,-1,-1,-1,63,52,53,54,55,56,57,58,59,60,61,-1,-1,-1,-1,-1,-1,
        -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,-1,-1,-1,-1,-1,
        -1,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1
    };
    std::vector<char> out;
    out.reserve(in.size() * 3 / 4);
    int val = 0, valb = -8;
    for (unsigned char c : in) {
        if (T[c] == -1) {
            if (c == '=') break;
            continue;
        }
        val = (val << 6) + T[c];
        valb += 6;
        if (valb >= 0) {
            out.push_back(char((val >> valb) & 0xFF));
            valb -= 8;
        }
    }
    return out;
}

static std::string RandomUuid() {
    static const char* hex = "0123456789abcdef";
    std::string s; s.reserve(36);
    for (int i = 0; i < 36; ++i) {
        if (i == 8 || i == 13 || i == 18 || i == 23) s += '-';
        else if (i == 14) s += '4';
        else if (i == 19) s += hex[(rand() & 3) | 8];
        else s += hex[rand() & 15];
    }
    return s;
}

static fs::path DetectLeagueGamePath(const std::string& hint = "") {
    auto is_valid_game_dir = [](const fs::path& p) -> bool {
        std::error_code ec;
        return fs::exists(p / "DATA" / "FINAL", ec);
        };

    if (!hint.empty()) {
        fs::path hp = PathFromUtf8(hint);
        if (is_valid_game_dir(hp)) return hp;
        if (is_valid_game_dir(hp / "Game")) return hp / "Game";
    }

    wchar_t envBuf[MAX_PATH] = {};
    DWORD envLen = GetEnvironmentVariableW(L"LTK_LEAGUE_PATH", envBuf, MAX_PATH);
    if (envLen > 0 && envLen < MAX_PATH) {
        fs::path ep(envBuf);
        if (is_valid_game_dir(ep)) return ep;
        if (is_valid_game_dir(ep / "Game")) return ep / "Game";
    }

    char sysDrive[16] = "C:";
    GetEnvironmentVariableA("SystemDrive", sysDrive, sizeof(sysDrive));
    fs::path installsJson = fs::path(sysDrive) / "ProgramData" / "Riot Games" / "RiotClientInstalls.json";
    std::error_code ec;
    if (fs::exists(installsJson, ec)) {
        std::ifstream f(installsJson);
        if (f) {
            std::string content((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
            mj::JVal root = mj::parse(content);
            if (auto* assoc = root.get("associated_client"); assoc && assoc->t == mj::JVal::OBJ) {
                for (auto const& [k, v] : assoc->obj) {
                    std::string lowerK = k;
                    for (char& c : lowerK) c = (char)tolower((unsigned char)c);
                    if (lowerK.find("league of legends") != std::string::npos && lowerK.find("pbe") == std::string::npos) {
                        fs::path candidate = PathFromUtf8(k);
                        if (is_valid_game_dir(candidate / "Game")) return candidate / "Game";
                        if (is_valid_game_dir(candidate)) return candidate;
                    }
                }
            }
        }
    }

    HANDLE hSnap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (hSnap != INVALID_HANDLE_VALUE) {
        PROCESSENTRY32W pe{};
        pe.dwSize = sizeof(pe);
        if (Process32FirstW(hSnap, &pe)) {
            do {
                if (_wcsicmp(pe.szExeFile, L"LeagueClientUx.exe") == 0 ||
                    _wcsicmp(pe.szExeFile, L"League of Legends.exe") == 0) {
                    HANDLE hProc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pe.th32ProcessID);
                    if (hProc) {
                        wchar_t exePath[MAX_PATH] = {};
                        DWORD sz = MAX_PATH;
                        if (QueryFullProcessImageNameW(hProc, 0, exePath, &sz)) {
                            fs::path p = fs::path(exePath).parent_path();
                            if (is_valid_game_dir(p)) { CloseHandle(hProc); CloseHandle(hSnap); return p; }
                            if (is_valid_game_dir(p / "Game")) { CloseHandle(hProc); CloseHandle(hSnap); return p / "Game"; }
                        }
                        CloseHandle(hProc);
                    }
                }
            } while (Process32NextW(hSnap, &pe));
        }
        CloseHandle(hSnap);
    }

    const char* drives[] = { "C:", "D:", "E:", "F:", "G:" };
    for (auto drive : drives) {
        fs::path p = fs::path(drive) / "Riot Games" / "League of Legends" / "Game";
        if (is_valid_game_dir(p)) return p;
    }

    return {};
}

struct WsClient {
    SOCKET s = INVALID_SOCKET;
    bool open = false;

    bool connect(const std::string& wsUrl) {
        std::string u = wsUrl;
        if (u.size() < 5 || u.compare(0, 5, "ws://") != 0) return false;
        u = u.substr(5);
        size_t slash = u.find('/');
        std::string hostport = (slash == std::string::npos) ? u : u.substr(0, slash);
        std::string path = (slash == std::string::npos) ? "/" : u.substr(slash);
        std::string host = hostport; int port = g_cdpPort;
        size_t colon = hostport.find(':');
        if (colon != std::string::npos) { host = hostport.substr(0, colon); port = atoi(hostport.c_str() + colon + 1); }

        addrinfo hints{}, * res = nullptr;
        hints.ai_family = AF_INET; hints.ai_socktype = SOCK_STREAM;
        char portStr[16]; snprintf(portStr, sizeof(portStr), "%d", port);
        if (getaddrinfo(host.c_str(), portStr, &hints, &res) != 0) return false;
        s = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
        if (s == INVALID_SOCKET) { freeaddrinfo(res); return false; }
        if (::connect(s, res->ai_addr, (int)res->ai_addrlen) != 0) {
            closesocket(s); s = INVALID_SOCKET; freeaddrinfo(res); return false;
        }
        freeaddrinfo(res);

        SetSocketTimeout(s, kSocketTimeoutWs);

        uint8_t keyRaw[16];
        for (int i = 0; i < 16; ++i) keyRaw[i] = (uint8_t)(rand() & 0xFF);
        std::string key = B64Enc(keyRaw, 16);
        // The one origin --remote-allow-origins lets in (see the launcher)
        char origin[64];
        snprintf(origin, sizeof(origin), "http://127.0.0.1:%d", g_cdpPort);
        std::string req =
            "GET " + path + " HTTP/1.1\r\nHost: " + host + ":" + portStr + "\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            "Origin: " + origin + "\r\n"
            "Sec-WebSocket-Key: " + key + "\r\nSec-WebSocket-Version: 13\r\n\r\n";
        send(s, req.c_str(), (int)req.size(), 0);

        std::string hdr; char b[1];
        while (hdr.find("\r\n\r\n") == std::string::npos) {
            int r = recv(s, b, 1, 0);
            if (r <= 0) { close(); return false; }
            hdr += b[0];
            if (hdr.size() > 8192) { close(); return false; }
        }
        if (hdr.find(" 101 ") == std::string::npos &&
            hdr.find(" 101\r") == std::string::npos) {
            close(); return false;
        }
        open = true;
        return true;
    }

    bool sendText(const std::string& t) {
        if (!open) return false;
        std::string frame;
        frame.push_back((char)0x81);
        size_t len = t.size();
        if (len < 126) frame.push_back((char)(0x80 | (uint8_t)len));
        else if (len < 65536) { frame.push_back((char)(0x80 | 126)); frame.push_back((char)((len >> 8) & 0xFF)); frame.push_back((char)(len & 0xFF)); }
        else { frame.push_back((char)(0x80 | 127)); for (int i = 7; i >= 0; --i) frame.push_back((char)((len >> (i * 8)) & 0xFF)); }
        uint8_t mk[4] = { (uint8_t)(rand() & 0xFF), (uint8_t)(rand() & 0xFF), (uint8_t)(rand() & 0xFF), (uint8_t)(rand() & 0xFF) };
        frame.append((char*)mk, 4);
        for (size_t i = 0; i < len; ++i) frame.push_back((char)(t[i] ^ mk[i % 4]));
        return send(s, frame.data(), (int)frame.size(), 0) == (int)frame.size();
    }

    bool recvExact(void* buf, size_t n) {
        size_t got = 0;
        while (got < n) {
            int r = recv(s, (char*)buf + got, (int)(n - got), 0);
            if (r <= 0) return false;
            got += (size_t)r;
        }
        return true;
    }

    std::string recvText() {
        std::string message;
        while (open) {
            uint8_t hdr[2];
            if (!recvExact(hdr, 2)) { open = false; return {}; }

            bool fin = (hdr[0] & 0x80) != 0;
            uint8_t opcode = hdr[0] & 0x0F;
            bool masked = (hdr[1] & 0x80) != 0;
            uint64_t len = hdr[1] & 0x7F;

            if (len == 126) {
                uint8_t b[2]; if (!recvExact(b, 2)) { open = false; return {}; }
                len = ((uint64_t)b[0] << 8) | b[1];
            }
            else if (len == 127) {
                uint8_t b[8]; if (!recvExact(b, 8)) { open = false; return {}; }
                len = 0; for (int i = 0; i < 8; ++i) len = (len << 8) | b[i];
            }
            if (len > 64 * 1024 * 1024) { open = false; return {}; }

            uint8_t mk[4] = {};
            if (masked && !recvExact(mk, 4)) { open = false; return {}; }

            std::string payload;
            if (len) {
                payload.resize((size_t)len);
                if (!recvExact(&payload[0], (size_t)len)) { open = false; return {}; }
                if (masked) for (size_t i = 0; i < len; ++i) payload[i] = (char)(payload[i] ^ mk[i % 4]);
            }

            if (opcode == 0x8) { open = false; return {}; }
            if (opcode == 0x9 || opcode == 0xA) continue;

            message += payload;
            if (fin) return message;
        }
        return {};
    }

    void close() {
        if (s != INVALID_SOCKET) { closesocket(s); s = INVALID_SOCKET; }
        open = false;
    }
};

static std::string HttpGet(int port, const char* path) {
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0);
    if (s == INVALID_SOCKET) return {};
    sockaddr_in a{}; a.sin_family = AF_INET; a.sin_port = htons((u_short)port);
    inet_pton(AF_INET, "127.0.0.1", &a.sin_addr);
    if (::connect(s, (sockaddr*)&a, sizeof(a)) != 0) { closesocket(s); return {}; }

    SetSocketTimeout(s, kSocketTimeoutHttp);

    char req[256];
    snprintf(req, sizeof(req), "GET %s HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n", path);
    send(s, req, (int)strlen(req), 0);

    std::string resp; char buf[4096]; int n;
    int expectedLen = -1;
    size_t hdrEnd = std::string::npos;

    while ((n = recv(s, buf, sizeof(buf), 0)) > 0) {
        resp.append(buf, n);
        if (hdrEnd == std::string::npos) {
            hdrEnd = resp.find("\r\n\r\n");
            if (hdrEnd != std::string::npos) {
                std::string h = resp.substr(0, hdrEnd);
                for (char& c : h) c = (char)tolower((unsigned char)c);
                size_t p = h.find("content-length:");
                if (p != std::string::npos) expectedLen = atoi(h.c_str() + p + 15);
            }
        }
        if (hdrEnd != std::string::npos && expectedLen >= 0) {
            if (resp.size() >= hdrEnd + 4 + expectedLen) break;
        }
    }
    closesocket(s);
    if (hdrEnd == std::string::npos) return {};
    return resp.substr(hdrEnd + 4);
}

static bool CdpAvailable() { return !HttpGet(g_cdpPort, "/json/version").empty(); }

// LTK Manager's own page only: whatever else answers on the port (another
// program's debugger) must never run LTK Manager's commands
static std::string CdpFindWsUrl() {
    std::string body = HttpGet(g_cdpPort, "/json");
    if (body.empty()) return {};
    mj::JVal arr = mj::parse(body);
    if (arr.t != mj::JVal::ARR) return {};
    for (auto& t : arr.arr) {
        if (t.get("type") && t.get("type")->asStr() == "page") {
            auto* url = t.get("url"); auto* wsu = t.get("webSocketDebuggerUrl");
            if (url && wsu && url->asStr().find("tauri.localhost") != std::string::npos) return wsu->asStr();
        }
    }
    return {};
}

static WsClient g_wsCache;
static int g_cdpId = 0;

static std::string CdpEvaluate(const std::string& jsExpr, DWORD timeoutMs = kCdpEvalBudgetMs) {
    if (!g_wsCache.open) {
        std::string wsUrl = CdpFindWsUrl();
        if (wsUrl.empty() || !g_wsCache.connect(wsUrl)) return {};
    }

    int myId = ++g_cdpId;
    mj::JVal req = mj::JVal::obj_();
    req.set("id", mj::JVal::num(myId));
    req.set("method", mj::JVal::str("Runtime.evaluate"));

    mj::JVal params = mj::JVal::obj_();
    params.set("expression", mj::JVal::str(jsExpr));
    params.set("awaitPromise", mj::JVal::boo(true));
    params.set("returnByValue", mj::JVal::boo(true));
    req.set("params", std::move(params));

    if (!g_wsCache.sendText(req.dump())) {
        g_wsCache.close();
        return {};
    }

    ULONGLONG start = GetTickCount64();
    while (GetTickCount64() - start < timeoutMs) {
        // Each wait gets what is left of the budget, so a slow command (an
        // install) is not cut off by the socket's own timeout
        ULONGLONG left = timeoutMs - (GetTickCount64() - start);
        SetSocketTimeout(g_wsCache.s, (DWORD)(left < 1000 ? 1000 : left));
        std::string frame = g_wsCache.recvText();
        if (frame.empty()) { g_wsCache.close(); return {}; }

        mj::JVal rsp = mj::parse(frame);
        auto* id = rsp.get("id");
        if (!id || id->asInt() != myId) continue;

        auto* resultPtr = rsp.get("result");
        if (!resultPtr) return frame;
        auto* inner = resultPtr->get("result");
        if (!inner) return frame;
        auto* val = inner->get("value");
        return val ? val->dump() : inner->dump();
    }

    g_wsCache.close();
    return {};
}

// Evaluates *js* (an expression yielding a JSON-able value) in LTK Manager's
// page, one evaluation at a time
static mj::JVal CdpEvaluateJson(const std::string& js, DWORD timeoutMs = kCdpEvalBudgetMs) {
    BOOL entered = FALSE;
    for (int i = 0; i < 100 && !entered; ++i) {
        entered = TryEnterCriticalSection(&g_cdpLock);
        if (!entered) Sleep(20);
    }
    if (!entered) {
        mj::JVal err = mj::JVal::obj_();
        err.set("ok", mj::JVal::boo(false));
        err.set("error", mj::JVal::str("CDP busy (another eval in progress)"));
        return err;
    }

    std::string raw;
    try { raw = CdpEvaluate(js, timeoutMs); }
    catch (...) { raw.clear(); }

    LeaveCriticalSection(&g_cdpLock);

    if (raw.empty()) {
        mj::JVal err = mj::JVal::obj_();
        err.set("ok", mj::JVal::boo(false));
        err.set("error", mj::JVal::str("CDP unavailable or timed out"));
        return err;
    }
    return mj::parse(raw);
}

static mj::JVal TauriInvoke(const std::string& command, const mj::JVal& args, DWORD timeoutMs = kCdpEvalBudgetMs) {
    std::string js =
        "(async () => { try { const r = await window.__TAURI_INTERNALS__.invoke("
        + mj::JVal::str(command).dump() + ", " + args.dump() +
        "); return r; } catch (e) { return { ok: false, error: (e && e.message) ? e.message : String(e) }; } })()";
    return CdpEvaluateJson(js, timeoutMs);
}

// LTK Manager checks every mod new to its library ("Automatically check mods",
// autoHealthCheckEnabled), and Rose installs the picked skin anew for each
// game: a check every game, minutes long on a hard drive, while the game loads
// (Rose#481). Turns the setting off as LTK Manager's settings page does: the
// whole settings read, the one field changed, saved back
static mj::JVal CmdHealthCheckOff() {
    const char* js = R"JS(
(async () => {
    try {
        const invoke = window.__TAURI_INTERNALS__.invoke;
        const got = await invoke('plugin:settings|get_settings');
        if (!got || got.ok === false) {
            return { ok: false, error: 'get_settings failed: ' + JSON.stringify(got && got.error) };
        }
        const settings = got.value !== undefined ? got.value : got;
        if (!settings || typeof settings !== 'object') return { ok: false, error: 'get_settings returned no settings' };
        if (settings.autoHealthCheckEnabled === false) return { ok: true, changed: false };
        settings.autoHealthCheckEnabled = false;
        const saved = await invoke('plugin:settings|save_settings', { settings });
        if (saved && saved.ok === false) {
            return { ok: false, error: 'save_settings failed: ' + JSON.stringify(saved.error) };
        }
        return { ok: true, changed: true };
    } catch (e) {
        return { ok: false, error: (e && e.message) ? e.message : String(e) };
    }
})()
)JS";
    mj::JVal r = CdpEvaluateJson(js);
    if (r.t != mj::JVal::OBJ) {
        mj::JVal err = mj::JVal::obj_();
        err.set("ok", mj::JVal::boo(false));
        err.set("error", mj::JVal::str("unexpected answer from LTK Manager's page"));
        return err;
    }
    return r;
}

// LTK Manager creates its window hidden and its frontend shows it once the page
// has mounted (Tauri's show_main_window, unless the user starts in the tray).
// Hiding it after the fact leaves it on screen for up to one poll interval -
// the flash seen when LTK Manager starts. So the process's own window-show
// calls are diverted here: its frame is never presented at all, and HideThread
// stays as the net for a window that is already visible (or not imported).
static BOOL (WINAPI* g_realShowWindow)(HWND, int) = nullptr;
static BOOL (WINAPI* g_realShowWindowAsync)(HWND, int) = nullptr;
static BOOL (WINAPI* g_realSetWindowPos)(HWND, HWND, int, int, int, int, UINT) = nullptr;
static BOOL (WINAPI* g_realSetWindowPlacement)(HWND, const WINDOWPLACEMENT*) = nullptr;
static LONG_PTR (WINAPI* g_realSetWindowLongPtrW)(HWND, int, LONG_PTR) = nullptr;
static LONG_PTR (WINAPI* g_realSetWindowLongPtrA)(HWND, int, LONG_PTR) = nullptr;
static LONG (WINAPI* g_realSetWindowLongW)(HWND, int, LONG) = nullptr;
static LONG (WINAPI* g_realSetWindowLongA)(HWND, int, LONG) = nullptr;
static volatile LONG g_showSuppressed = 0;

// The window HideThread would hide: this process's, no owner (a dialog or a
// menu belongs to the app and keeps its show)
static bool IsOwnTopLevelWindow(HWND hwnd) {
    if (hwnd == nullptr || !IsWindow(hwnd)) return false;
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (pid != GetCurrentProcessId()) return false;
    return GetWindow(hwnd, GW_OWNER) == nullptr && GetParent(hwnd) == nullptr;
}

static void NoteSuppressedShow() {
    if (InterlockedExchange(&g_showSuppressed, 1) == 0)
        ApiLog("[Hide] suppressed a show of the LTK Manager window");
}

static BOOL WINAPI ShowWindowHidden(HWND hwnd, int cmd) {
    if (cmd != SW_HIDE && IsOwnTopLevelWindow(hwnd)) {
        NoteSuppressedShow();
        return g_realShowWindow(hwnd, SW_HIDE);
    }
    return g_realShowWindow(hwnd, cmd);
}

static BOOL WINAPI ShowWindowAsyncHidden(HWND hwnd, int cmd) {
    if (cmd != SW_HIDE && IsOwnTopLevelWindow(hwnd)) {
        NoteSuppressedShow();
        return g_realShowWindowAsync(hwnd, SW_HIDE);
    }
    return g_realShowWindowAsync(hwnd, cmd);
}

// tao shows a window through more than ShowWindow: dropping SWP_SHOWWINDOW
// keeps the same move/resize call from presenting it
static BOOL WINAPI SetWindowPosHidden(HWND hwnd, HWND after, int x, int y, int cx, int cy, UINT flags) {
    if ((flags & SWP_SHOWWINDOW) != 0 && IsOwnTopLevelWindow(hwnd)) {
        NoteSuppressedShow();
        flags &= ~SWP_SHOWWINDOW;
    }
    return g_realSetWindowPos(hwnd, after, x, y, cx, cy, flags);
}

// The window-state plugin restores a placement, whose showCmd would present
// the window as well
static BOOL WINAPI SetWindowPlacementHidden(HWND hwnd, const WINDOWPLACEMENT* placement) {
    if (placement != nullptr && placement->showCmd != SW_HIDE && IsOwnTopLevelWindow(hwnd)) {
        WINDOWPLACEMENT hidden = *placement;
        hidden.showCmd = SW_HIDE;
        NoteSuppressedShow();
        return g_realSetWindowPlacement(hwnd, &hidden);
    }
    return g_realSetWindowPlacement(hwnd, placement);
}

// tao applies a window flag (VISIBLE among them) as a style change followed by
// SetWindowPos(SWP_FRAMECHANGED), which presents the window without ever
// asking SetWindowPos to show it: drop WS_VISIBLE from the style instead
static LONG_PTR WINAPI SetWindowLongPtrHiddenW(HWND hwnd, int index, LONG_PTR value) {
    if (index == GWL_STYLE && (value & WS_VISIBLE) != 0 && IsOwnTopLevelWindow(hwnd)) {
        NoteSuppressedShow();
        value &= ~static_cast<LONG_PTR>(WS_VISIBLE);
    }
    return g_realSetWindowLongPtrW(hwnd, index, value);
}

static LONG_PTR WINAPI SetWindowLongPtrHiddenA(HWND hwnd, int index, LONG_PTR value) {
    if (index == GWL_STYLE && (value & WS_VISIBLE) != 0 && IsOwnTopLevelWindow(hwnd)) {
        NoteSuppressedShow();
        value &= ~static_cast<LONG_PTR>(WS_VISIBLE);
    }
    return g_realSetWindowLongPtrA(hwnd, index, value);
}

// 32-bit setters: a style fits in a LONG, so tao applies the window flags
// through these even on x64
static LONG WINAPI SetWindowLongHiddenW(HWND hwnd, int index, LONG value) {
    if (index == GWL_STYLE && (value & WS_VISIBLE) != 0 && IsOwnTopLevelWindow(hwnd)) {
        NoteSuppressedShow();
        value &= ~WS_VISIBLE;
    }
    return g_realSetWindowLongW(hwnd, index, value);
}

static LONG WINAPI SetWindowLongHiddenA(HWND hwnd, int index, LONG value) {
    if (index == GWL_STYLE && (value & WS_VISIBLE) != 0 && IsOwnTopLevelWindow(hwnd)) {
        NoteSuppressedShow();
        value &= ~WS_VISIBLE;
    }
    return g_realSetWindowLongA(hwnd, index, value);
}

// Replace every import slot of ltk-manager.exe that resolves to *api*.
static int PatchImport(HMODULE module, const char* api, PROC detour, PROC* real) {
    PROC target = GetProcAddress(module, api);
    if (target == nullptr) return 0;
    *real = target;

    auto* base = reinterpret_cast<uint8_t*>(GetModuleHandleW(nullptr));
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return 0;
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return 0;
    const IMAGE_DATA_DIRECTORY& dir =
        nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (dir.VirtualAddress == 0 || dir.Size == 0) return 0;

    int patched = 0;
    auto* desc = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(base + dir.VirtualAddress);
    for (; desc->Name != 0; ++desc) {
        auto* slot = reinterpret_cast<IMAGE_THUNK_DATA*>(base + desc->FirstThunk);
        for (; slot->u1.Function != 0; ++slot) {
            if (reinterpret_cast<void*>(slot->u1.Function) != reinterpret_cast<void*>(target))
                continue;
            DWORD old = 0;
            if (!VirtualProtect(&slot->u1.Function, sizeof(slot->u1.Function), PAGE_READWRITE, &old))
                continue;
            slot->u1.Function = reinterpret_cast<ULONGLONG>(detour);
            VirtualProtect(&slot->u1.Function, sizeof(slot->u1.Function), old, &old);
            ++patched;
        }
    }
    return patched;
}

// The exe is ltk-manager.exe itself (the launcher injects this before the CRT
// runs), so these imports are the window-show paths its frontend can take.
static bool PatchWindowShowImports() {
    HMODULE user32 = GetModuleHandleW(L"user32.dll");
    if (!user32) return false;
    int patched = 0;
    patched += PatchImport(user32, "ShowWindow", (PROC)&ShowWindowHidden, (PROC*)&g_realShowWindow);
    patched += PatchImport(user32, "ShowWindowAsync", (PROC)&ShowWindowAsyncHidden, (PROC*)&g_realShowWindowAsync);
    patched += PatchImport(user32, "SetWindowPos", (PROC)&SetWindowPosHidden, (PROC*)&g_realSetWindowPos);
    patched += PatchImport(user32, "SetWindowPlacement", (PROC)&SetWindowPlacementHidden,
                           (PROC*)&g_realSetWindowPlacement);
    patched += PatchImport(user32, "SetWindowLongPtrW", (PROC)&SetWindowLongPtrHiddenW,
                           (PROC*)&g_realSetWindowLongPtrW);
    patched += PatchImport(user32, "SetWindowLongPtrA", (PROC)&SetWindowLongPtrHiddenA,
                           (PROC*)&g_realSetWindowLongPtrA);
    patched += PatchImport(user32, "SetWindowLongW", (PROC)&SetWindowLongHiddenW,
                           (PROC*)&g_realSetWindowLongW);
    patched += PatchImport(user32, "SetWindowLongA", (PROC)&SetWindowLongHiddenA,
                           (PROC*)&g_realSetWindowLongA);
    if (patched > 0)
        ApiLog("[Hide] %d window-show import(s) patched - the LTK Manager window stays hidden", patched);
    else
        ApiLog("[Hide] no window-show import found in this build - falling back to the polling hide");
    return patched > 0;
}

static BOOL CALLBACK HideOneWindowInternal(HWND hwnd, LPARAM lp) {
    DWORD pid = (DWORD)lp; DWORD wpid = 0;
    GetWindowThreadProcessId(hwnd, &wpid);
    if (wpid != pid) return TRUE;
    if (GetWindow(hwnd, GW_OWNER) != NULL) return TRUE;
    if (!IsWindowVisible(hwnd)) return TRUE;
    ShowWindow(hwnd, SW_HIDE);
    return TRUE;
}
static DWORD WINAPI HideThread(LPVOID) {
    DWORD pid = GetCurrentProcessId();
    while (WaitForSingleObject(g_hStopEvt, 100) == WAIT_TIMEOUT)
        EnumWindows(HideOneWindowInternal, (LPARAM)pid);
    return 0;
}

static bool WriteTextFile(const std::wstring& path, const std::string& text) {
    std::wstring tmp = path + L".tmp";
    HANDLE h = CreateFileW(tmp.c_str(), GENERIC_WRITE, 0, NULL,
        CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD w = 0;
    BOOL ok = WriteFile(h, text.data(), (DWORD)text.size(), &w, NULL);
    CloseHandle(h);
    if (!ok) { DeleteFileW(tmp.c_str()); return false; }
    return MoveFileExW(tmp.c_str(), path.c_str(),
        MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != 0;
}
// %LOCALAPPDATA%\LTKBridge (empty when the variable is missing)
static std::wstring LocalBridgeDir() {
    wchar_t localApp[MAX_PATH];
    DWORD n = GetEnvironmentVariableW(L"LOCALAPPDATA", localApp, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return {};
    return std::wstring(localApp) + L"\\LTKBridge";
}
static void MakeApiToken() {
    uint8_t raw[16] = {};
    if (BCryptGenRandom(NULL, raw, sizeof(raw), BCRYPT_USE_SYSTEM_PREFERRED_RNG) != 0) {
        for (auto& b : raw) b = (uint8_t)(rand() & 0xFF);
    }
    static const char* hex = "0123456789abcdef";
    for (int i = 0; i < 16; ++i) {
        g_apiToken[i * 2] = hex[raw[i] >> 4];
        g_apiToken[i * 2 + 1] = hex[raw[i] & 15];
    }
    g_apiToken[32] = 0;
}
static bool TokenMatches(const std::string& given) {
    size_t n = strlen(g_apiToken);
    if (n == 0 || given.size() != n) return false;
    unsigned char diff = 0;
    for (size_t i = 0; i < n; ++i) diff |= (unsigned char)(given[i] ^ g_apiToken[i]);
    return diff == 0;
}
// The port goes everywhere a client looks for it; the token only where the
// user's own processes (and an elevated Rose) can read it: the user's
// registry hive and local app data, never the Public folder
static void BroadcastPort(int port) {
    char portText[16];
    snprintf(portText, sizeof(portText), "%d\n", port);
    HKEY hk;
    if (RegCreateKeyExA(HKEY_CURRENT_USER, "Software\\LTKBridge", 0, NULL, 0,
        KEY_WRITE, NULL, &hk, NULL) == ERROR_SUCCESS) {
        DWORD v = (DWORD)port;
        RegSetValueExA(hk, "ApiPort", 0, REG_DWORD, (BYTE*)&v, sizeof(v));
        RegSetValueExA(hk, "ApiToken", 0, REG_SZ, (BYTE*)g_apiToken, (DWORD)strlen(g_apiToken) + 1);
        RegCloseKey(hk);
    }
    std::wstring dir = LocalBridgeDir();
    if (!dir.empty()) {
        CreateDirectoryW(dir.c_str(), NULL);
        WriteTextFile(dir + L"\\port.txt", portText);
        WriteTextFile(dir + L"\\token.txt", std::string(g_apiToken) + "\n");
    }
    WriteTextFile(L"C:\\Users\\Public\\LTKBridge.port", portText);
}
static void ClearPortBroadcast() {
    HKEY hk;
    if (RegOpenKeyExA(HKEY_CURRENT_USER, "Software\\LTKBridge", 0,
        KEY_WRITE, &hk) == ERROR_SUCCESS) {
        RegDeleteValueA(hk, "ApiPort");
        RegDeleteValueA(hk, "ApiToken");
        RegCloseKey(hk);
    }
    std::wstring dir = LocalBridgeDir();
    if (!dir.empty()) {
        DeleteFileW((dir + L"\\port.txt").c_str());
        DeleteFileW((dir + L"\\token.txt").c_str());
    }
    DeleteFileW(L"C:\\Users\\Public\\LTKBridge.port");
}

static mj::JVal CmdSpoofHealth() {
    const char* js = R"JS(
(function() {
    if (window.__ltk_health_spoofed) return 'already';
    if (!window.__TAURI_INTERNALS__ || !window.__TAURI_INTERNALS__.invoke) return '';
    window.__ltk_health_spoofed = true;
    const orig = window.__TAURI_INTERNALS__.invoke;
    window.__TAURI_INTERNALS__.invoke = async function(cmd, args) {
        if (cmd === 'plugin:library|get_mod_health_verdicts') {
            const v = {};
            try {
                const lib = await orig.call(this, 'plugin:library|get_installed_mods', {});
                const list = (lib && lib.value) ? lib.value : (Array.isArray(lib) ? lib : []);
                if (Array.isArray(list)) {
                    for (const m of list) {
                        if (m && m.id) v[m.id] = { modId: m.id, health: 'healthy' };
                    }
                }
            } catch (e) {}
            const uuid = (crypto.randomUUID ? crypto.randomUUID() : '00000000-0000-4000-8000-000000000000');
            if (Object.keys(v).length === 0) {
                v[uuid] = { modId: uuid, health: 'healthy' };
            }
            return { ok: true, value: v };
        }
        return orig.apply(this, arguments);
    };
    return 'ok';
})()
)JS";
    BOOL entered = FALSE;
    for (int i = 0; i < 100 && !entered; ++i) {
        entered = TryEnterCriticalSection(&g_cdpLock);
        if (!entered) Sleep(20);
    }
    std::string raw;
    if (entered) {
        try { raw = CdpEvaluate(js); }
        catch (...) { raw.clear(); }
        LeaveCriticalSection(&g_cdpLock);
    }
    bool ok = (raw.find("ok") != std::string::npos || raw.find("already") != std::string::npos);
    mj::JVal r = mj::JVal::obj_();
    r.set("ok", mj::JVal::boo(ok));
    r.set("raw", mj::JVal::str(raw));
    return r;
}

static DWORD WINAPI AutoSpoofHealthThread(LPVOID) {
    while (WaitForSingleObject(g_hStopEvt, 500) == WAIT_TIMEOUT) {
        if (!CdpAvailable()) continue;
        mj::JVal res = CmdSpoofHealth();
        if (res.get("ok") && res.get("ok")->asBool()) {
            ApiLog("[AutoSpoofHealth] Installed health spoof shim by default");
            if (WaitForSingleObject(g_hStopEvt, 5000) != WAIT_TIMEOUT) break;
        }
    }
    return 0;
}

static mj::JVal CmdStatus() {
    mj::JVal r = mj::JVal::obj_();
    r.set("ok", mj::JVal::boo(true));
    r.set("pid", mj::JVal::num((double)GetCurrentProcessId()));

    mj::JVal cdp = mj::JVal::obj_();
    cdp.set("port", mj::JVal::num(g_cdpPort));
    cdp.set("available", mj::JVal::boo(CdpAvailable()));
    r.set("cdp", std::move(cdp));

    mj::JVal api = mj::JVal::obj_();
    api.set("tcp_port", mj::JVal::num((double)g_apiPort));
    api.set("tcp_ok", mj::JVal::boo(g_apiPort != 0));
    r.set("api", std::move(api));

    fs::path gameDir = DetectLeagueGamePath();
    r.set("league_game_path", mj::JVal::str(PathToUtf8(gameDir)));
    return r;
}

static mj::JVal CmdList() {
    mj::JVal resp = TauriInvoke(kLibGetInstalledMods, mj::JVal::obj_());
    auto* ok = resp.get("ok");
    mj::JVal r = mj::JVal::obj_();
    if (ok && ok->asBool()) {
        r.set("ok", mj::JVal::boo(true));
        auto* val = resp.get("value");
        r.set("library", val ? *val : mj::JVal::arr_());
        r.set("raw", resp);
    }
    else {
        r.set("ok", mj::JVal::boo(false));
        r.set("raw", resp);
    }
    return r;
}

static mj::JVal ImportError(const std::string& message) {
    mj::JVal r = mj::JVal::obj_();
    r.set("ok", mj::JVal::boo(false));
    r.set("error", mj::JVal::str(message));
    return r;
}

// A file name LTK Manager can install from: no path separators or
// characters Windows refuses, and the archive's extension
static std::wstring StagedFileName(const std::wstring& name) {
    std::wstring out;
    for (wchar_t c : name) {
        if (c < 32 || wcschr(L"<>:\"/\\|?*", c)) out += L'_';
        else out += c;
    }
    while (!out.empty() && (out.back() == L'.' || out.back() == L' ')) out.pop_back();
    if (out.empty()) out = L"ImportedMod";
    std::wstring lower = out;
    for (auto& ch : lower) ch = (wchar_t)towlower(ch);
    auto endsWith = [&](const wchar_t* ext) {
        size_t n = wcslen(ext);
        return lower.size() >= n && lower.compare(lower.size() - n, n, ext) == 0;
        };
    if (!endsWith(L".fantome") && !endsWith(L".modpkg")) out += L".fantome";
    return out;
}

static mj::JVal CmdImport(const mj::JVal& req) {
    std::string path = req.get("path") ? req.get("path")->asStr() : "";
    std::string dataB64 = req.get("data_b64") ? req.get("data_b64")->asStr() : "";
    std::string customName = req.get("name") ? req.get("name")->asStr() : "ImportedMod.fantome";

    // The archive goes to LTK Manager as Rose packed it. UTF-8, as LTK
    // Manager's install command receives it
    std::string installPath = path;
    // Created for an archive sent as bytes, removed once LTK Manager has
    // copied it into its library
    fs::path stagingDir;

    if (!dataB64.empty()) {
        std::vector<char> bytes = B64Dec(dataB64);
        if (bytes.empty()) return ImportError("invalid base64 in 'data_b64'");
        // LTK Manager installs from a file
        std::error_code ec;
        stagingDir = fs::temp_directory_path(ec) / "LTKBridge_Staging" / RandomUuid();
        if (!ec) fs::create_directories(stagingDir, ec);
        fs::path staged = stagingDir / StagedFileName(Utf8ToWide(customName));
        bool written = false;
        if (!ec) {
            std::ofstream out(staged, std::ios::binary);
            written = out && out.write(bytes.data(), (std::streamsize)bytes.size());
        }
        if (!written) {
            fs::remove_all(stagingDir, ec);
            return ImportError("could not stage the archive for LTK Manager");
        }
        installPath = PathToUtf8(staged);
    }
    else if (!path.empty()) {
        fs::path source = PathFromUtf8(path);
        if (GetFileAttributesW(source.c_str()) == INVALID_FILE_ATTRIBUTES) {
            DWORD err = GetLastError();
            // Rose sends the bytes instead when this process cannot read
            // the file (overlay_manager.py)
            if (err == ERROR_FILE_NOT_FOUND || err == ERROR_PATH_NOT_FOUND)
                return ImportError("not found: " + path);
            return ImportError("cannot read file: " + path + " (Windows error " + std::to_string(err) + ")");
        }
        std::ifstream f(source, std::ios::binary);
        if (!f) return ImportError("failed to read file: " + path);
    }
    else {
        return ImportError("missing 'path' or 'data_b64'");
    }

    CmdSpoofHealth();

    mj::JVal args = mj::JVal::obj_();
    args.set("filePath", mj::JVal::str(installPath));
    mj::JVal resp = TauriInvoke(kLibInstallMod, args, kCdpInstallBudgetMs);

    if (!stagingDir.empty()) {
        std::error_code ec;
        fs::remove_all(stagingDir, ec);
    }

    mj::JVal r = mj::JVal::obj_();
    r.set("ok", resp.get("ok") ? *resp.get("ok") : mj::JVal::boo(true));
    if (auto* err = resp.get("error")) r.set("error", *err);
    r.set("response", resp);
    return r;
}

static mj::JVal CmdToggle(const std::string& target, bool enable) {
    if (target.empty()) {
        mj::JVal r = mj::JVal::obj_();
        r.set("ok", mj::JVal::boo(false)); r.set("error", mj::JVal::str("missing 'target'"));
        return r;
    }
    std::string modId = target;
    mj::JVal libResp = TauriInvoke(kLibGetInstalledMods, mj::JVal::obj_());
    auto* libVal = libResp.get("value");
    if (libVal && libVal->t == mj::JVal::ARR) {
        for (auto& m : libVal->arr) {
            auto* id = m.get("id"); if (!id) continue;
            if (id->asStr() == target) { modId = target; break; }
            auto* nm = m.get("displayName");
            auto* sn = m.get("name");
            std::string a = target; for (auto& c : a) c = (char)tolower((unsigned char)c);
            if (nm) {
                std::string b = nm->asStr(); for (auto& c : b) c = (char)tolower((unsigned char)c);
                if (a == b) { modId = id->asStr(); break; }
            }
            if (sn) {
                std::string b = sn->asStr(); for (auto& c : b) c = (char)tolower((unsigned char)c);
                if (a == b) { modId = id->asStr(); break; }
            }
        }
    }
    mj::JVal args = mj::JVal::obj_();
    args.set("modId", mj::JVal::str(modId));
    args.set("enabled", mj::JVal::boo(enable));
    mj::JVal resp = TauriInvoke(kLibToggleMod, args);
    mj::JVal r = mj::JVal::obj_();
    r.set("ok", resp.get("ok") ? *resp.get("ok") : mj::JVal::boo(true));
    r.set("modId", mj::JVal::str(modId));
    r.set("response", resp);
    return r;
}

static mj::JVal CmdUninstall(const std::string& target) {
    if (target.empty()) {
        mj::JVal r = mj::JVal::obj_();
        r.set("ok", mj::JVal::boo(false)); r.set("error", mj::JVal::str("missing 'target'"));
        return r;
    }
    std::string modId = target;
    mj::JVal libResp = TauriInvoke(kLibGetInstalledMods, mj::JVal::obj_());
    auto* libVal = libResp.get("value");
    if (libVal && libVal->t == mj::JVal::ARR) {
        for (auto& m : libVal->arr) {
            auto* id = m.get("id"); if (!id) continue;
            if (id->asStr() == target) { modId = target; break; }
            auto* nm = m.get("displayName");
            auto* sn = m.get("name");
            std::string a = target; for (auto& c : a) c = (char)tolower((unsigned char)c);
            if (nm) {
                std::string b = nm->asStr(); for (auto& c : b) c = (char)tolower((unsigned char)c);
                if (a == b) { modId = id->asStr(); break; }
            }
            if (sn) {
                std::string b = sn->asStr(); for (auto& c : b) c = (char)tolower((unsigned char)c);
                if (a == b) { modId = id->asStr(); break; }
            }
        }
    }
    mj::JVal args = mj::JVal::obj_();
    args.set("modId", mj::JVal::str(modId));
    mj::JVal resp = TauriInvoke(kLibUninstallMod, args);
    mj::JVal r = mj::JVal::obj_();
    r.set("ok", resp.get("ok") ? *resp.get("ok") : mj::JVal::boo(true));
    r.set("modId", mj::JVal::str(modId));
    r.set("response", resp);
    return r;
}

static mj::JVal CmdHealth(const std::string& requestedModId) {
    std::string modId = requestedModId.empty() ? RandomUuid() : requestedModId;
    mj::JVal entry = mj::JVal::obj_();
    entry.set("modId", mj::JVal::str(modId));
    entry.set("health", mj::JVal::str("healthy"));
    mj::JVal value = mj::JVal::obj_();
    value.set(modId, entry);
    mj::JVal r = mj::JVal::obj_();
    r.set("ok", mj::JVal::boo(true));
    r.set("value", value);
    return r;
}

static mj::JVal CmdStartPatcher() {
    CmdSpoofHealth();
    mj::JVal args = mj::JVal::obj_();
    args.set("config", mj::JVal::obj_());
    mj::JVal resp = TauriInvoke(kPatStartPatcher, args);
    mj::JVal r = mj::JVal::obj_();
    r.set("ok", resp.get("ok") ? *resp.get("ok") : mj::JVal::boo(true));
    r.set("response", resp); return r;
}
static mj::JVal CmdStopPatcher() {
    mj::JVal resp = TauriInvoke(kPatStopPatcher, mj::JVal::obj_());
    mj::JVal r = mj::JVal::obj_();
    r.set("ok", resp.get("ok") ? *resp.get("ok") : mj::JVal::boo(true));
    r.set("response", resp); return r;
}
static mj::JVal CmdPatcherStatus() {
    mj::JVal resp = TauriInvoke(kPatGetPatcherStatus, mj::JVal::obj_());
    mj::JVal r = mj::JVal::obj_();
    r.set("ok", resp.get("ok") ? *resp.get("ok") : mj::JVal::boo(true));
    r.set("response", resp); return r;
}

static DWORD WINAPI KillThread(LPVOID) {
    Sleep(200);
    ExitProcess(0);
    return 0;
}
static mj::JVal CmdKill() {
    HANDLE th = CreateThread(NULL, 0, KillThread, NULL, 0, NULL);
    if (th) CloseHandle(th);
    mj::JVal r = mj::JVal::obj_();
    r.set("ok", mj::JVal::boo(true));
    r.set("message", mj::JVal::str("terminating host process in 200 ms"));
    return r;
}

static std::string HandleCommand(const std::string& line) {
    mj::JVal req = mj::parse(line);
    if (req.t != mj::JVal::OBJ) {
        mj::JVal r = mj::JVal::obj_();
        r.set("ok", mj::JVal::boo(false)); r.set("error", mj::JVal::str("invalid JSON"));
        return r.dump();
    }
    auto* cmd = req.get("cmd"); std::string c = cmd ? cmd->asStr() : "";

    if (c == "hello") {
        mj::JVal r = mj::JVal::obj_();
        r.set("ok", mj::JVal::boo(true));
        r.set("service", mj::JVal::str("LTKBridge"));
        r.set("version", mj::JVal::str("1.1-fantome-processor"));
        r.set("pid", mj::JVal::num((double)GetCurrentProcessId()));
        r.set("port", mj::JVal::num((double)g_apiPort));
        r.set("auth", mj::JVal::boo(true));
        r.set("credit", mj::JVal::str(kCredit));
        return r.dump();
    }
    if (c == "ping") { mj::JVal r = mj::JVal::obj_(); r.set("ok", mj::JVal::boo(true)); r.set("pong", mj::JVal::num((double)GetTickCount64())); return r.dump(); }

    // Everything else drives LTK Manager. The port also takes lines a web
    // page POSTs to it, so a command needs the token, which only the user's
    // own processes can read (BroadcastPort)
    auto* token = req.get("token");
    if (!token || !TokenMatches(token->asStr())) {
        mj::JVal r = mj::JVal::obj_();
        r.set("ok", mj::JVal::boo(false)); r.set("error", mj::JVal::str("unauthorized: missing or wrong token"));
        return r.dump();
    }

    if (c == "status")         return CmdStatus().dump();
    if (c == "list")           return CmdList().dump();
    if (c == "import")         return CmdImport(req).dump();
    if (c == "toggle")         return CmdToggle(req.get("target") ? req.get("target")->asStr() : "",
        req.get("enabled") ? req.get("enabled")->asBool() : true).dump();
    if (c == "uninstall")      return CmdUninstall(req.get("target") ? req.get("target")->asStr() : "").dump();
    if (c == "health")         return CmdHealth(req.get("modId") ? req.get("modId")->asStr() : "").dump();
    if (c == "spoof_health")   return CmdSpoofHealth().dump();
    if (c == "health_check_off") return CmdHealthCheckOff().dump();
    if (c == "start_patcher")  return CmdStartPatcher().dump();
    if (c == "stop_patcher")   return CmdStopPatcher().dump();
    if (c == "patcher_status") return CmdPatcherStatus().dump();
    if (c == "kill")           return CmdKill().dump();

    mj::JVal r = mj::JVal::obj_();
    r.set("ok", mj::JVal::boo(false)); r.set("error", mj::JVal::str("unknown: " + c));
    return r.dump();
}

static DWORD WINAPI TcpClientThread(LPVOID param) {
    SOCKET c = (SOCKET)(uintptr_t)param;
    std::string buf; char chunk[4096];

    while (true) {
        int r = recv(c, chunk, sizeof(chunk), 0);
        if (r <= 0) break;

        try {
            buf.append(chunk, r);
            if (buf.size() > 64 * 1024 * 1024) break;

            size_t nl;
            while ((nl = buf.find('\n')) != std::string::npos) {
                std::string line = buf.substr(0, nl);
                buf.erase(0, nl + 1);
                if (!line.empty() && line.back() == '\r') line.pop_back();
                if (line.empty()) continue;

                std::string resp = HandleCommand(line) + "\n";
                if (send(c, resp.data(), (int)resp.size(), 0) <= 0) goto done;
            }
        }
        catch (...) { break; }
    }
done:
    shutdown(c, SD_BOTH);
    closesocket(c);
    return 0;
}

static SOCKET TryBindPort(int port) {
    SOCKET ls = socket(AF_INET, SOCK_STREAM, 0);
    if (ls == INVALID_SOCKET) return INVALID_SOCKET;
    BOOL exclusive = TRUE;
    setsockopt(ls, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, (char*)&exclusive, sizeof(exclusive));
    sockaddr_in a{}; a.sin_family = AF_INET; a.sin_port = htons((u_short)port);
    inet_pton(AF_INET, "127.0.0.1", &a.sin_addr);
    if (bind(ls, (sockaddr*)&a, sizeof(a)) != 0) { closesocket(ls); return INVALID_SOCKET; }
    if (listen(ls, SOMAXCONN) != 0) { closesocket(ls); return INVALID_SOCKET; }
    return ls;
}

static DWORD WINAPI TcpServerThread(LPVOID) {
    int rangeStart = kApiPortStart, rangeEnd = kApiPortEnd;
    char envPort[16] = {};
    if (GetEnvironmentVariableA("LTK_API_PORT", envPort, 16) > 0 ||
        GetEnvironmentVariableA("CELESTIAL_API_PORT", envPort, 16) > 0) {
        int p = atoi(envPort);
        if (p > 0 && p < 65536) { rangeStart = rangeEnd = p; }
    }
    SOCKET ls = INVALID_SOCKET;
    for (int p = rangeStart; p <= rangeEnd; ++p) {
        ls = TryBindPort(p);
        if (ls != INVALID_SOCKET) { g_apiPort = p; break; }
    }
    if (ls == INVALID_SOCKET) {
        ApiLog("[TcpServer] Failed to bind any port in %d..%d", rangeStart, rangeEnd);
        return 0;
    }

    ApiLog("[TcpServer] Listening on 127.0.0.1:%d (PID=%lu)", g_apiPort, GetCurrentProcessId());
    MakeApiToken();
    BroadcastPort(g_apiPort);

    while (WaitForSingleObject(g_hStopEvt, 0) != WAIT_OBJECT_0) {
        fd_set rs; FD_ZERO(&rs); FD_SET(ls, &rs);
        timeval tv{ 0, 200000 };
        int r = select(0, &rs, NULL, NULL, &tv);
        if (r <= 0) continue;
        SOCKET c = accept(ls, NULL, NULL);
        if (c == INVALID_SOCKET) continue;
        HANDLE th = CreateThread(NULL, 0, TcpClientThread, (LPVOID)(uintptr_t)c, 0, NULL);
        if (th) CloseHandle(th);
        else closesocket(c);
    }
    closesocket(ls);
    g_apiPort = 0;
    return 0;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        if (InterlockedCompareExchange(&g_dllAttached, 1, 0) != 0) return TRUE;
        DisableThreadLibraryCalls(hModule);
        ResolveApiLog();
        LogInit(g_apiLog);

        srand((unsigned)GetTickCount64() ^ (unsigned)GetCurrentProcessId());
        InitializeCriticalSection(&g_cdpLock);

        wchar_t skip[8] = {};
        BOOL noCdp = (GetEnvironmentVariableW(L"LTK_NO_CDP", skip, 8) != 0) ||
            (GetEnvironmentVariableW(L"CELESTIAL_NO_CDP", skip, 8) != 0);
        if (!noCdp) SetupCdpPort();

        WSADATA wsa; WSAStartup(MAKEWORD(2, 2), &wsa);

        g_hStopEvt = CreateEventA(NULL, TRUE, FALSE, NULL);
        HANDLE t = CreateThread(NULL, 0, TcpServerThread, NULL, 0, NULL);
        if (t) CloseHandle(t);

        HANDLE thSpoof = CreateThread(NULL, 0, AutoSpoofHealthThread, NULL, 0, NULL);
        if (thSpoof) CloseHandle(thSpoof);

        wchar_t noHide[8] = {};
        BOOL hide = (GetEnvironmentVariableW(L"LTK_NO_HIDE", noHide, 8) == 0) &&
            (GetEnvironmentVariableW(L"CELESTIAL_NO_HIDE", noHide, 8) == 0);
        if (hide) {
            // Before the window exists: a show that arrives before the first
            // poll's hide is the flash this prevents
            PatchWindowShowImports();
            HANDLE th = CreateThread(NULL, 0, HideThread, NULL, 0, NULL);
            if (th) CloseHandle(th);
        }
    }
    else if (reason == DLL_PROCESS_DETACH) {
        ApiLog("[DllMain] DLL_PROCESS_DETACH in PID=%lu", GetCurrentProcessId());
        if (g_hStopEvt) SetEvent(g_hStopEvt);
        g_wsCache.close();
    }
    return TRUE;
}
