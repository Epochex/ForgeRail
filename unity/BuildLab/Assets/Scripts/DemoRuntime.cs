using System;
using System.Collections;
using System.IO;
using System.Text;
using UnityEngine;

namespace GameBuild
{
    [Serializable]
    public sealed class DemoConfiguration
    {
        public string title;
        public float move_speed;
        public string resource_version;
    }

    public sealed class DemoRuntime : MonoBehaviour
    {
        public Transform avatar;
        private BuildInfo info;
        private DemoConfiguration config;
        private string error;
        private bool loaded;

        private IEnumerator Start()
        {
            var smokeOutput = Argument("--smoke-output");
            try
            {
                var directory = Path.Combine(Application.streamingAssetsPath,"GameBuild");
                info = JsonUtility.FromJson<BuildInfo>(File.ReadAllText(Path.Combine(directory,"build-info.json")));
                if (info == null || string.IsNullOrEmpty(info.build_id)) throw new Exception("Embedded build identity is missing");
                var bundlePath = Path.Combine(directory,"demo");
                if (BuildContracts.Sha256(File.ReadAllBytes(bundlePath)) != info.bundle_sha256)
                    throw new Exception("AssetBundle SHA256 mismatch");
                var bundle = AssetBundle.LoadFromFile(bundlePath);
                if (bundle == null) throw new Exception("AssetBundle.LoadFromFile failed");
                try
                {
                    var text = bundle.LoadAsset<TextAsset>("demo-config");
                    if (text == null) throw new Exception("AssetBundle config is missing");
                    if (BuildContracts.Sha256(text.bytes) != info.config_sha256) throw new Exception("Configuration SHA256 mismatch");
                    config = JsonUtility.FromJson<DemoConfiguration>(text.text);
                    if (config == null || config.move_speed <= 0 || string.IsNullOrEmpty(config.resource_version))
                        throw new Exception("AssetBundle config is invalid");
                    loaded = true;
                }
                finally { bundle.Unload(false); }
            }
            catch (Exception exception) { error=exception.Message; Debug.LogException(exception); }
            // Start and one frame completed; headless smoke does not assert rendering correctness.
            yield return null;
            if (!string.IsNullOrEmpty(smokeOutput))
            {
                try
                {
                    var receipt = info == null ? new SmokeReceipt() : JsonUtility.FromJson<SmokeReceipt>(JsonUtility.ToJson(info));
                    receipt.asset_loaded=loaded;
                    receipt.status=loaded ? "passed" : "failed";
                    receipt.error=error;
                    receipt.started_at=DateTime.UtcNow.ToString("O");
                    var output = Path.GetFullPath(smokeOutput);
                    Directory.CreateDirectory(Path.GetDirectoryName(output));
                    File.WriteAllText(output + ".tmp",JsonUtility.ToJson(receipt,true),new UTF8Encoding(false));
                    File.Move(output + ".tmp",output);
                    Debug.Log("GAMEBUILD_SMOKE_" + (loaded ? "PASS" : "FAIL"));
                }
                catch (Exception exception) { loaded=false; Debug.LogException(exception); }
                Application.Quit(loaded ? 0 : 1);
            }
        }

        private void Update()
        {
            if (!loaded || avatar == null) return;
            var x = (Input.GetKey(KeyCode.D) || Input.GetKey(KeyCode.RightArrow) ? 1 : 0) - (Input.GetKey(KeyCode.A) || Input.GetKey(KeyCode.LeftArrow) ? 1 : 0);
            var z = (Input.GetKey(KeyCode.W) || Input.GetKey(KeyCode.UpArrow) ? 1 : 0) - (Input.GetKey(KeyCode.S) || Input.GetKey(KeyCode.DownArrow) ? 1 : 0);
            avatar.position += new Vector3(x,0,z) * (config.move_speed * Time.deltaTime);
        }

        private void OnGUI()
        {
            GUI.Box(new Rect(16,16,650,156),"Game Build Lab");
            GUI.Label(new Rect(30,46,610,24), info == null ? "Loading identity..." : "Build: " + info.build_id);
            GUI.Label(new Rect(30,70,610,24), info == null ? "" : "Commit: " + info.commit_sha);
            GUI.Label(new Rect(30,94,610,24),loaded ? "Bundle loaded: " + config.resource_version : "Error: " + error);
            GUI.Label(new Rect(30,118,610,24),"Move the cube with WASD / arrow keys");
        }

        private static string Argument(string key)
        {
            var args = Environment.GetCommandLineArgs();
            for (var i=0;i<args.Length-1;i++) if (args[i] == key) return args[i+1];
            return null;
        }
    }
}
