/*
 * Stand-in for cslol-dll.dll.
 *
 * mod-tools.exe links cslol-dll.dll at load time, so Windows refuses to start
 * it without a DLL of that name, even for "mkoverlay", which never calls into
 * it. Rose serves overlays through the user-provided LTK patcher instead of
 * "runoverlay", so these exports only need to exist. None of them do anything;
 * each reports failure in case something calls it anyway.
 */

#include <stddef.h>

#define EXPORT __declspec(dllexport)

static const char stub_error[] = "cslol-dll stub: runoverlay is not supported by Rose";

EXPORT const char* cslol_init(void) { return stub_error; }
EXPORT const char* cslol_set_config(const wchar_t* prefix) { (void)prefix; return stub_error; }
EXPORT const char* cslol_set_flags(unsigned long long flags) { (void)flags; return stub_error; }
EXPORT const char* cslol_set_log_level(unsigned int level) { (void)level; return stub_error; }
EXPORT unsigned int cslol_find(void) { return 0; }
EXPORT const char* cslol_hook(unsigned int tid, unsigned int timeout, unsigned int step) {
    (void)tid; (void)timeout; (void)step;
    return stub_error;
}
EXPORT const char* cslol_log_pull(void) { return NULL; }
