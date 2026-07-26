using System;
using Microsoft.VisualStudio.TestTools.UnitTesting;
using PenguLoader.Main;

namespace PenguLoader.Tests
{
    [TestClass]
    public class IfeoIntegrationTest
    {
        [TestMethod]
        public void OptIn_fake_target_preserves_sentinel_and_key()
        {
            if (!string.Equals(Environment.GetEnvironmentVariable("ROSE_PENGU_IFEO_INTEGRATION"), "1", StringComparison.Ordinal))
                Assert.Inconclusive("Set ROSE_PENGU_IFEO_INTEGRATION=1 to run the administrator-only IFEO test.");

            var target = Environment.GetEnvironmentVariable("ROSE_PENGU_IFEO_TARGET");
            if (string.IsNullOrWhiteSpace(target) || !target.StartsWith("RosePenguIntegration-", StringComparison.Ordinal))
                Assert.Fail("The integration target must begin with RosePenguIntegration-.");

            var api = new Win32RegistryApi();
            var oldApi = IFEO.RegistryApi;
            IFEO.RegistryApi = api;
            try
            {
                IRegistryHandle ifeo;
                Assert.AreEqual(0, api.OpenLocalMachine(IFEO.IFEO_PATH, Win32Registry.KEY_CREATE_SUB_KEY, out ifeo));
                using (ifeo)
                {
                    IRegistryHandle targetKey;
                    uint disposition;
                    Assert.AreEqual(0, api.CreateSubKey(ifeo, target, Win32Registry.KEY_SET_VALUE, out targetKey, out disposition));
                    using (targetKey)
                        Assert.AreEqual(0, api.SetString(targetKey, "RoseSentinel", "preserve-me"));
                }

                var modulePath = typeof(IfeoIntegrationTest).Assembly.Location;
                var activated = IFEO.Activate(target, modulePath);
                Assert.IsTrue(activated.Succeeded, activated.ToOfficialStyleString());
                Assert.AreEqual("rundll32 \"" + modulePath + "\", #6000", ReadValue(api, target, "Debugger"));
                Assert.AreEqual("preserve-me", ReadValue(api, target, "RoseSentinel"));

                var deactivated = IFEO.Deactivate(target);
                Assert.IsTrue(deactivated.Succeeded, deactivated.ToOfficialStyleString());
                Assert.AreEqual(Win32Registry.ERROR_FILE_NOT_FOUND, ReadValueCode(api, target, "Debugger"));
                Assert.AreEqual("preserve-me", ReadValue(api, target, "RoseSentinel"));
                Assert.AreEqual(0, api.OpenLocalMachine(IFEO.IFEO_PATH + "\\" + target, Win32Registry.KEY_QUERY_VALUE, out var preservedKey));
                preservedKey.Dispose();
            }
            finally
            {
                try
                {
                    IRegistryHandle parent;
                    var openResult = api.OpenLocalMachine(
                        IFEO.IFEO_PATH,
                        Win32Registry.KEY_WRITE,
                        out parent);
                    if (openResult != Win32Registry.ERROR_SUCCESS &&
                        openResult != Win32Registry.ERROR_FILE_NOT_FOUND &&
                        openResult != Win32Registry.ERROR_PATH_NOT_FOUND)
                    {
                        Assert.Fail("Unable to open the guarded IFEO parent for cleanup: " + openResult);
                    }
                    else if (openResult == Win32Registry.ERROR_SUCCESS)
                    {
                        using (parent)
                        {
                            var deleteResult = api.DeleteSubKey(parent, target);
                            if (deleteResult != Win32Registry.ERROR_SUCCESS &&
                                deleteResult != Win32Registry.ERROR_FILE_NOT_FOUND &&
                                deleteResult != Win32Registry.ERROR_PATH_NOT_FOUND)
                            {
                                Assert.Fail("Unable to remove the guarded IFEO target: " + deleteResult);
                            }
                        }
                    }
                }
                finally
                {
                    IFEO.RegistryApi = oldApi;
                }
            }
        }

        private static string ReadValue(Win32RegistryApi api, string target, string name)
        {
            IRegistryHandle key;
            Assert.AreEqual(0, api.OpenLocalMachine(IFEO.IFEO_PATH + "\\" + target, Win32Registry.KEY_QUERY_VALUE, out key));
            using (key)
            {
                string value;
                Assert.AreEqual(0, api.QueryString(key, name, out value));
                return value;
            }
        }

        private static int ReadValueCode(Win32RegistryApi api, string target, string name)
        {
            IRegistryHandle key;
            Assert.AreEqual(0, api.OpenLocalMachine(IFEO.IFEO_PATH + "\\" + target, Win32Registry.KEY_QUERY_VALUE, out key));
            using (key)
            {
                string value;
                return api.QueryString(key, name, out value);
            }
        }
    }
}
