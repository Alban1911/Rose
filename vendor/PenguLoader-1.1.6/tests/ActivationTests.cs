using System;
using System.Collections.Generic;
using Microsoft.VisualStudio.TestTools.UnitTesting;
using PenguLoader.Main;

namespace PenguLoader.Tests
{
    [TestClass]
    public class ActivationTests
    {
        private IRegistryApi _oldRegistryApi;

        [TestInitialize]
        public void SetUp()
        {
            _oldRegistryApi = IFEO.RegistryApi;
        }

        [TestCleanup]
        public void TearDown()
        {
            IFEO.RegistryApi = _oldRegistryApi;
        }

        [TestMethod]
        public void DebuggerCommand_has_exact_official_format()
        {
            Assert.AreEqual(
                "rundll32 \"C:\\Rose\\Pengu Loader\\core.dll\", #6000",
                IFEO.BuildDebuggerCommand("C:\\Rose\\Pengu Loader\\core.dll"));
        }

        [TestMethod]
        public void DebuggerCommand_has_no_trailing_space()
        {
            StringAssert.DoesNotMatch(IFEO.BuildDebuggerCommand("C:\\Rose\\core.dll"),
                new System.Text.RegularExpressions.Regex(@"\s$"));
        }

        [TestMethod]
        public void ExtractQuotedPath_extracts_first_quoted_path()
        {
            Assert.AreEqual("C:\\Rose\\core.dll", IFEO.ExtractQuotedPath("rundll32 \"C:\\Rose\\core.dll\", #6000"));
        }

        [TestMethod]
        public void ExtractQuotedPath_returns_null_without_quotes()
        {
            Assert.IsNull(IFEO.ExtractQuotedPath("rundll32 C:\\Rose\\core.dll, #6000"));
        }

        [TestMethod]
        public void ExtractQuotedPath_returns_null_with_unclosed_quote()
        {
            Assert.IsNull(IFEO.ExtractQuotedPath("rundll32 \"C:\\Rose\\core.dll, #6000"));
        }

        [TestMethod]
        public void NormalizePath_is_case_insensitive_and_converts_forward_slashes()
        {
            Assert.AreEqual("c:\\rose\\core.dll", IFEO.NormalizePath("C:/ROSE/core.dll"));
        }

        [TestMethod]
        public void ActivationResult_failure_round_trips_stage_and_kind()
        {
            var result = ActivationResult.Failure(
                ActivationStage.SetDebugger,
                ActivationErrorKind.PermissionDenied,
                5,
                "Access is denied.");
            var decoded = ActivationResult.DecodeExitCode(result.EncodeExitCode());
            Assert.IsFalse(decoded.Succeeded);
            Assert.AreEqual(ActivationStage.SetDebugger, decoded.Stage);
            Assert.AreEqual(ActivationErrorKind.PermissionDenied, decoded.ErrorKind);
            Assert.AreEqual("SetDebugger (permission_denied)", result.ToOfficialStyleString());
        }

        [TestMethod]
        public void Activate_uses_exact_registry_access_masks()
        {
            var fake = new FakeRegistryApi();
            IFEO.RegistryApi = fake;

            var result = IFEO.Activate("LeagueClientUx.exe", "C:\\Rose\\core.dll");

            Assert.IsTrue(result.Succeeded);
            Assert.AreEqual(Win32Registry.KEY_CREATE_SUB_KEY, fake.OpenAccess);
            Assert.AreEqual(Win32Registry.KEY_SET_VALUE, fake.CreateAccess);
            Assert.AreEqual("rundll32 \"C:\\Rose\\core.dll\", #6000", fake.Value);
        }

        [TestMethod]
        public void Status_uses_query_value_only()
        {
            var fake = new FakeRegistryApi { Value = "rundll32 \"C:\\Rose\\core.dll\", #6000" };
            IFEO.RegistryApi = fake;

            Assert.IsTrue(IFEO.IsActivated("LeagueClientUx.exe", "C:\\Rose\\core.dll"));
            Assert.AreEqual(Win32Registry.KEY_QUERY_VALUE, fake.OpenAccess);
        }

        [TestMethod]
        public void Deactivate_deletes_only_Debugger_value()
        {
            var fake = new FakeRegistryApi();
            IFEO.RegistryApi = fake;

            var result = IFEO.Deactivate("LeagueClientUx.exe");

            Assert.IsTrue(result.Succeeded);
            Assert.AreEqual(Win32Registry.KEY_SET_VALUE, fake.OpenAccess);
            Assert.AreEqual("Debugger", fake.DeletedValueName);
            Assert.IsFalse(fake.TargetDeleted);
        }

        [TestMethod]
        public void Native_failures_retain_their_activation_stage()
        {
            var fake = new FakeRegistryApi { OpenResult = 5 };
            IFEO.RegistryApi = fake;
            var result = IFEO.Activate("LeagueClientUx.exe", "C:\\Rose\\core.dll");
            Assert.AreEqual(ActivationStage.OpenIFEO, result.Stage);
            Assert.AreEqual(ActivationErrorKind.PermissionDenied, result.ErrorKind);
        }

        private sealed class FakeRegistryApi : IRegistryApi
        {
            public uint OpenAccess { get; private set; }
            public uint CreateAccess { get; private set; }
            public int OpenResult { get; set; }
            public string Value { get; set; }
            public string DeletedValueName { get; private set; }
            public bool TargetDeleted { get; private set; }

            public int OpenLocalMachine(string path, uint desiredAccess, out IRegistryHandle handle)
            {
                OpenAccess = desiredAccess;
                handle = OpenResult == 0 ? new FakeHandle() : null;
                return OpenResult;
            }

            public int CreateSubKey(IRegistryHandle parent, string name, uint desiredAccess,
                out IRegistryHandle handle, out uint disposition)
            {
                CreateAccess = desiredAccess;
                disposition = Win32Registry.REG_OPENED_EXISTING_KEY;
                handle = new FakeHandle();
                return 0;
            }

            public int QueryString(IRegistryHandle key, string valueName, out string value)
            {
                value = Value;
                return Value == null ? Win32Registry.ERROR_FILE_NOT_FOUND : 0;
            }

            public int SetString(IRegistryHandle key, string valueName, string value)
            {
                Value = value;
                return 0;
            }

            public int DeleteValue(IRegistryHandle key, string valueName)
            {
                DeletedValueName = valueName;
                return 0;
            }
        }

        private sealed class FakeHandle : IRegistryHandle
        {
            public IntPtr NativeHandle { get { return IntPtr.Zero; } }
            public void Dispose() { }
        }
    }
}
