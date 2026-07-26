using System;
using Microsoft.VisualStudio.TestTools.UnitTesting;
using PenguLoader.Main;

namespace PenguLoader.Tests
{
    [TestClass]
    public class ActivationContractAdditionalTests
    {
        [TestMethod]
        public void ActivationResult_success_encodes_zero()
        {
            Assert.AreEqual(0, ActivationResult.Success().EncodeExitCode());
        }

        [TestMethod]
        public void Each_stage_round_trips_through_exit_code()
        {
            foreach (ActivationStage stage in Enum.GetValues(typeof(ActivationStage)))
            {
                if (stage == ActivationStage.None)
                    continue;
                var result = ActivationResult.Failure(stage, ActivationErrorKind.Other, 0, "failure");
                Assert.AreEqual(stage, ActivationResult.DecodeExitCode(result.EncodeExitCode()).Stage);
            }
        }

        [TestMethod]
        public void Unknown_error_kind_round_trips()
        {
            var kind = (ActivationErrorKind)42;
            var result = ActivationResult.Failure(ActivationStage.SetDebugger, kind, 0, "failure");
            Assert.AreEqual(kind, ActivationResult.DecodeExitCode(result.EncodeExitCode()).ErrorKind);
        }

        [TestMethod]
        public void IsActivated_requires_matching_rundll32_quoted_path()
        {
            var fake = new RegistryFake { Value = "rundll32 \"C:/Rose/core.dll\", #6000" };
            var old = IFEO.RegistryApi;
            IFEO.RegistryApi = fake;
            try
            {
                Assert.IsTrue(IFEO.IsActivated("LeagueClientUx.exe", "c:\\rose\\core.dll"));
                fake.Value = "other.exe \"C:/Rose/core.dll\"";
                Assert.IsFalse(IFEO.IsActivated("LeagueClientUx.exe", "c:\\rose\\core.dll"));
                fake.Value = "rundll32 C:/Rose/core.dll, #6000";
                Assert.IsFalse(IFEO.IsActivated("LeagueClientUx.exe", "c:\\rose\\core.dll"));
                fake.Value = "rundll32 \"C:/Other/core.dll\", #6000";
                Assert.IsFalse(IFEO.IsActivated("LeagueClientUx.exe", "c:\\rose\\core.dll"));
            }
            finally { IFEO.RegistryApi = old; }
        }

        [TestMethod]
        public void Activation_stages_are_preserved_for_injected_failures()
        {
            var old = IFEO.RegistryApi;
            try
            {
                var fake = new RegistryFake { CreateResult = 5 };
                IFEO.RegistryApi = fake;
                Assert.AreEqual(ActivationStage.CreateTarget, IFEO.Activate("LeagueClientUx.exe", "C:\\Rose\\core.dll").Stage);

                fake = new RegistryFake { SetResult = 5 };
                IFEO.RegistryApi = fake;
                Assert.AreEqual(ActivationStage.SetDebugger, IFEO.Activate("LeagueClientUx.exe", "C:\\Rose\\core.dll").Stage);

                fake = new RegistryFake { DeleteResult = 5 };
                IFEO.RegistryApi = fake;
                Assert.AreEqual(ActivationStage.DeleteDebugger, IFEO.Deactivate("LeagueClientUx.exe").Stage);
            }
            finally { IFEO.RegistryApi = old; }
        }

        [TestMethod]
        public void Deactivate_missing_value_is_idempotent()
        {
            var fake = new RegistryFake { DeleteResult = Win32Registry.ERROR_FILE_NOT_FOUND };
            var old = IFEO.RegistryApi;
            IFEO.RegistryApi = fake;
            try { Assert.IsTrue(IFEO.Deactivate("LeagueClientUx.exe").Succeeded); }
            finally { IFEO.RegistryApi = old; }
        }

        [TestMethod]
        public void Parent_decodes_child_exit_code()
        {
            var old = Elevation.ProcessRunner;
            Elevation.ProcessRunner = new ProcessFake(ElevatedProcessResult.Completed(
                ActivationResult.Failure(ActivationStage.SetDebugger, ActivationErrorKind.PermissionDenied, 5, "denied").EncodeExitCode()));
            try
            {
                var result = Elevation.RunElevated(true, true);
                Assert.AreEqual(ActivationStage.SetDebugger, result.Stage);
                Assert.AreEqual(ActivationErrorKind.PermissionDenied, result.ErrorKind);
            }
            finally { Elevation.ProcessRunner = old; }
        }

        [TestMethod]
        public void Uac_cancel_maps_to_RunElevated_cancelled()
        {
            var old = Elevation.ProcessRunner;
            Elevation.ProcessRunner = new ProcessFake(ElevatedProcessResult.Failed(1223, "cancelled"));
            try
            {
                var result = Elevation.RunElevated(true, true);
                Assert.AreEqual(ActivationStage.RunElevated, result.Stage);
                Assert.AreEqual(ActivationErrorKind.Cancelled, result.ErrorKind);
            }
            finally { Elevation.ProcessRunner = old; }
        }

        [TestMethod]
        public void Process_start_failure_maps_to_RunElevated()
        {
            var old = Elevation.ProcessRunner;
            Elevation.ProcessRunner = new ProcessFake(ElevatedProcessResult.Failed(5, "denied"));
            try
            {
                var result = Elevation.RunElevated(false, true);
                Assert.AreEqual(ActivationStage.RunElevated, result.Stage);
                Assert.AreEqual(ActivationErrorKind.PermissionDenied, result.ErrorKind);
            }
            finally { Elevation.ProcessRunner = old; }
        }

        [TestMethod]
        public void WriteCoreConfig_failure_decodes_as_partial_state()
        {
            var result = ActivationResult.Failure(
                ActivationStage.WriteCoreConfig,
                ActivationErrorKind.Other,
                5,
                "config denied",
                true);
            var decoded = ActivationResult.DecodeExitCode(result.EncodeExitCode());
            Assert.AreEqual(ActivationStage.WriteCoreConfig, decoded.Stage);
            Assert.IsTrue(decoded.PartialState);
        }

        [TestMethod]
        public void Config_failure_is_reported_after_registry_success_and_marks_partial_state()
        {
            var oldApi = IFEO.RegistryApi;
            var oldElevatedOverride = Elevation.IsElevatedOverride;
            var oldConfigWriter = Module.ConfigWriter;
            var fake = new RegistryFake();
            var configCalled = false;
            IFEO.RegistryApi = fake;
            Elevation.IsElevatedOverride = () => true;
            Config.SetRuntimeUseSymlink(false);
            Module.ConfigWriter = (section, key, value, path) =>
            {
                configCalled = true;
                return false;
            };

            try
            {
                var result = Module.SetActive(true);
                Assert.AreEqual(ActivationStage.WriteCoreConfig, result.Stage);
                Assert.IsTrue(result.PartialState);
                Assert.IsTrue(configCalled);
                Assert.IsNotNull(fake.Value);
            }
            finally
            {
                Module.ConfigWriter = oldConfigWriter;
                Elevation.IsElevatedOverride = oldElevatedOverride;
                Config.SetRuntimeUseSymlink(false);
                IFEO.RegistryApi = oldApi;
            }
        }

        [TestMethod]
        public void Registry_failure_does_not_write_core_config()
        {
            var oldApi = IFEO.RegistryApi;
            var oldElevatedOverride = Elevation.IsElevatedOverride;
            var oldConfigWriter = Module.ConfigWriter;
            var fake = new RegistryFake { SetResult = 5 };
            var configCalled = false;
            IFEO.RegistryApi = fake;
            Elevation.IsElevatedOverride = () => true;
            Config.SetRuntimeUseSymlink(false);
            Module.ConfigWriter = (section, key, value, path) =>
            {
                configCalled = true;
                return true;
            };

            try
            {
                var result = Module.SetActive(true);
                Assert.AreEqual(ActivationStage.SetDebugger, result.Stage);
                Assert.IsFalse(configCalled);
            }
            finally
            {
                Module.ConfigWriter = oldConfigWriter;
                Elevation.IsElevatedOverride = oldElevatedOverride;
                Config.SetRuntimeUseSymlink(false);
                IFEO.RegistryApi = oldApi;
            }
        }

        [TestMethod]
        public void Unelevated_parent_does_not_acquire_operation_mutex()
        {
            var oldOverride = Elevation.IsElevatedOverride;
            var oldProcessRunner = Elevation.ProcessRunner;
            var oldMutexFactory = Program.OperationMutexFactory;
            var oldInstallCore = Program.InstallCoreOverride;
            var process = new RecordingProcessFake();
            var mutexCreated = false;
            Elevation.IsElevatedOverride = () => false;
            Elevation.ProcessRunner = process;
            Program.OperationMutexFactory = () =>
            {
                mutexCreated = true;
                return new OperationMutexFake(true);
            };
            Program.InstallCoreOverride = active => ActivationResult.Success();

            try
            {
                var result = Program.RequestActivation(true);
                Assert.IsTrue(result.Succeeded);
                Assert.IsFalse(mutexCreated);
                Assert.AreEqual("--install --silent", process.Arguments);
            }
            finally
            {
                Program.InstallCoreOverride = oldInstallCore;
                Program.OperationMutexFactory = oldMutexFactory;
                Elevation.ProcessRunner = oldProcessRunner;
                Elevation.IsElevatedOverride = oldOverride;
            }
        }

        [TestMethod]
        public void Elevated_child_acquires_mutex_without_launching_another_child()
        {
            var oldOverride = Elevation.IsElevatedOverride;
            var oldProcessRunner = Elevation.ProcessRunner;
            var oldMutexFactory = Program.OperationMutexFactory;
            var oldInstallCore = Program.InstallCoreOverride;
            var process = new RecordingProcessFake();
            var mutexCreated = false;
            var installCoreCalled = false;
            Elevation.IsElevatedOverride = () => true;
            Elevation.ProcessRunner = process;
            Program.OperationMutexFactory = () =>
            {
                mutexCreated = true;
                return new OperationMutexFake(true);
            };
            Program.InstallCoreOverride = active =>
            {
                installCoreCalled = true;
                return ActivationResult.Success();
            };

            try
            {
                var result = Program.RequestActivation(true);
                Assert.IsTrue(result.Succeeded);
                Assert.IsTrue(mutexCreated);
                Assert.IsTrue(installCoreCalled);
                Assert.IsNull(process.Arguments);
            }
            finally
            {
                Program.InstallCoreOverride = oldInstallCore;
                Program.OperationMutexFactory = oldMutexFactory;
                Elevation.ProcessRunner = oldProcessRunner;
                Elevation.IsElevatedOverride = oldOverride;
            }
        }
        private sealed class RecordingProcessFake : IElevatedProcessRunner
        {
            public string Arguments { get; private set; }

            public ElevatedProcessResult Run(string executable, string arguments, string workingDirectory)
            {
                Arguments = arguments;
                return ElevatedProcessResult.Completed(0);
            }
        }

        private sealed class OperationMutexFake : Program.IOperationMutex
        {
            public bool CreatedNew { get; }

            public OperationMutexFake(bool createdNew)
            {
                CreatedNew = createdNew;
            }

            public void Dispose() { }
        }
        private sealed class ProcessFake : IElevatedProcessRunner
        {
            private readonly ElevatedProcessResult _result;
            public ProcessFake(ElevatedProcessResult result) { _result = result; }
            public ElevatedProcessResult Run(string executable, string arguments, string workingDirectory) { return _result; }
        }

        private sealed class RegistryFake : IRegistryApi
        {
            public int OpenResult { get; set; }
            public int CreateResult { get; set; }
            public int SetResult { get; set; }
            public int DeleteResult { get; set; }
            public string Value { get; set; }

            public int OpenLocalMachine(string path, uint desiredAccess, out IRegistryHandle handle)
            {
                handle = OpenResult == 0 ? new Handle() : null;
                return OpenResult;
            }

            public int CreateSubKey(IRegistryHandle parent, string name, uint desiredAccess,
                out IRegistryHandle handle, out uint disposition)
            {
                disposition = Win32Registry.REG_OPENED_EXISTING_KEY;
                handle = CreateResult == 0 ? new Handle() : null;
                return CreateResult;
            }

            public int QueryString(IRegistryHandle key, string valueName, out string value)
            {
                value = Value;
                return Value == null ? Win32Registry.ERROR_FILE_NOT_FOUND : 0;
            }

            public int SetString(IRegistryHandle key, string valueName, string value)
            {
                Value = value;
                return SetResult;
            }

            public int DeleteValue(IRegistryHandle key, string valueName) { Value = null; return DeleteResult; }

            public int DeleteSubKey(IRegistryHandle parent, string name) { return Win32Registry.ERROR_SUCCESS; }
        }

        private sealed class Handle : IRegistryHandle
        {
            public IntPtr NativeHandle { get { return IntPtr.Zero; } }
            public void Dispose() { }
        }
    }
}
