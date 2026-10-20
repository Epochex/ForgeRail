using System;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace GameBuild
{
    [Serializable]
    public sealed class ResourceDependency
    {
        public string path;
        public string sha256;
        public string meta_sha256;
    }

    [Serializable]
    public sealed class EngineReport
    {
        public string adapter = "unity";
        public string status;
        public string result;
        public string build_id;
        public string commit_sha;
        public string input_digest;
        public string unity_version;
        public string target;
        public string configuration;
        public string started_at;
        public double duration_seconds;
        public ulong total_size;
        public int total_errors;
        public int total_warnings;
        public string error;
        public AssetIssue[] issues;
        public string[] resource_dependencies;
        public ResourceDependency[] resource_inputs;
        public string resource_input_digest;
        public string exporter_version = "gamebuild-bundle-v1";
        public string exporter_sha256;
        public bool resource_cache_hit;
        public double resource_cache_lookup_seconds;
        public double resource_export_seconds;
        public string bundle_sha256;
        public long bundle_bytes;
    }

    public static class BuildEntry
    {
        private const string Version = "6000.3.0f1";
        private const string ScenePath = "Assets/Generated/Runtime.unity";

        public static string Argument(string key)
        {
            var args=Environment.GetCommandLineArgs();
            for (var i=0;i<args.Length-1;i++) if (args[i] == key) return args[i+1];
            return null;
        }

        public static void Build()
        {
            var started=DateTime.UtcNow;
            var report=new EngineReport { status="failed", result="Failed", unity_version=Application.unityVersion, started_at=started.ToString("O") };
            string output=null;
            try
            {
                var requestPath=Argument("-buildRequest");
                if (string.IsNullOrEmpty(requestPath)) throw new ArgumentException("-buildRequest <json> is required");
                var request=JsonUtility.FromJson<BuildRequest>(File.ReadAllText(requestPath));
                BuildContracts.ValidateRequest(request,Directory.GetParent(Application.dataPath).FullName);
                if (Application.unityVersion != Version) throw new Exception("Unity version mismatch; required " + Version);
                output=Path.GetFullPath(request.output_dir);
                if (File.Exists(Path.Combine(output,"build-report.json")) || Directory.Exists(Path.Combine(output,"player")))
                { output=null; throw new Exception("Refusing to overwrite a prior build output"); }
                Directory.CreateDirectory(output);
                report.build_id=request.build_id; report.commit_sha=request.commit_sha; report.input_digest=request.input_digest;
                report.target=request.target; report.configuration=request.configuration;
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
                // Existing user scenes/prefabs are checked before generated scene replacement.
                report.issues=AssetChecks.ValidateAssets().ToArray();
                if (report.issues.Length != 0) throw new Exception("Unity resource check failed");
                GenerateScene();
                report.issues=AssetChecks.ValidateAssets().ToArray();
                if (report.issues.Length != 0) throw new Exception("Generated scene resource check failed");
                var streaming="Assets/StreamingAssets/GameBuild";
                Directory.CreateDirectory(streaming);
                var bundles=Path.Combine(output,"bundles");
                Directory.CreateDirectory(bundles);
                report.resource_dependencies=AssetDatabase.GetDependencies(AssetChecks.ConfigurationAsset,true).OrderBy(x=>x,StringComparer.Ordinal).ToArray();
                report.resource_inputs=report.resource_dependencies.Where(File.Exists).Select(path=>new ResourceDependency {
                    path=path, sha256=BuildContracts.Sha256(File.ReadAllBytes(path)),
                    meta_sha256=File.Exists(path + ".meta") ? BuildContracts.Sha256(File.ReadAllBytes(path + ".meta")) : ""
                }).ToArray();
                report.exporter_sha256=BuildContracts.Sha256(File.ReadAllBytes("Assets/Editor/BuildEntry.cs"));
                var resourceIdentity=Application.unityVersion + "\nStandaloneWindows64\n" + report.exporter_version + ":" + report.exporter_sha256 + "\n" +
                    string.Join("\n",report.resource_inputs.Select(x=>x.path + ":" + x.sha256 + ":" + x.meta_sha256));
                report.resource_input_digest=BuildContracts.Sha256(Encoding.UTF8.GetBytes(resourceIdentity));
                var cacheRoot=Argument("-assetCacheDir") ?? Path.Combine(Directory.GetParent(Application.dataPath).FullName,"Library","GameBuildBundleCache");
                var lookupStarted=DateTime.UtcNow;
                report.resource_cache_hit=BundleCache.TryRestore(cacheRoot,report.resource_input_digest,bundles);
                report.resource_cache_lookup_seconds=(DateTime.UtcNow-lookupStarted).TotalSeconds;
                if (!report.resource_cache_hit)
                {
                    var exportStarted=DateTime.UtcNow;
                    var map=new [] {new AssetBundleBuild { assetBundleName="demo", assetNames=new []{AssetChecks.ConfigurationAsset}, addressableNames=new []{"demo-config"} }};
                    var manifest=BuildPipeline.BuildAssetBundles(bundles,map,BuildAssetBundleOptions.ChunkBasedCompression | BuildAssetBundleOptions.StrictMode,BuildTarget.StandaloneWindows64);
                    if (manifest == null || !File.Exists(Path.Combine(bundles,"demo"))) throw new Exception("AssetBundle export failed");
                    report.resource_export_seconds=(DateTime.UtcNow-exportStarted).TotalSeconds;
                    BundleCache.Publish(cacheRoot,report.resource_input_digest,bundles);
                }
                var bundleBytes=File.ReadAllBytes(Path.Combine(bundles,"demo"));
                report.bundle_sha256=BuildContracts.Sha256(bundleBytes); report.bundle_bytes=bundleBytes.LongLength;
                File.WriteAllBytes(Path.Combine(streaming,"demo"),bundleBytes);
                var info=new BuildInfo {build_id=request.build_id,commit_sha=request.commit_sha,input_digest=request.input_digest,target=request.target,
                    configuration=request.configuration,unity_version=Application.unityVersion,
                    config_sha256=BuildContracts.Sha256(File.ReadAllBytes(AssetChecks.ConfigurationAsset)),bundle_sha256=report.bundle_sha256};
                WriteJson(Path.Combine(streaming,"build-info.json"),info);
                WriteJson(Path.Combine(output,"build-info.json"),info);
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
                PlayerSettings.companyName="GameBuildLab";
                PlayerSettings.productName="GameBuildLab";
                PlayerSettings.defaultScreenWidth=960; PlayerSettings.defaultScreenHeight=540;
                PlayerSettings.fullScreenMode=FullScreenMode.Windowed;
                PlayerSettings.runInBackground=true;
                PlayerSettings.SetScriptingBackend(NamedBuildTarget.Standalone,ScriptingImplementation.Mono2x);
                var options=request.configuration == "Release" ? BuildOptions.None : BuildOptions.Development;
                var build=BuildPipeline.BuildPlayer(new BuildPlayerOptions {scenes=new[]{ScenePath},locationPathName=Path.Combine(output,"player","GameBuildLab.exe"),target=BuildTarget.StandaloneWindows64,options=options});
                report.result=build.summary.result.ToString(); report.total_errors=build.summary.totalErrors;
                report.total_warnings=build.summary.totalWarnings; report.total_size=build.summary.totalSize;
                if (build.summary.result != BuildResult.Succeeded) throw new Exception("BuildPipeline.BuildPlayer failed: " + build.summary.result);
                report.status="passed";
            }
            catch (Exception exception)
            {
                report.error=exception.ToString();
                Debug.LogException(exception);
                throw;
            }
            finally
            {
                report.duration_seconds=(DateTime.UtcNow-started).TotalSeconds;
                if (output != null) WriteJson(Path.Combine(output,"build-report.json"),report);
            }
        }

        private static void WriteJson(string path, object data)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
            File.WriteAllText(path,JsonUtility.ToJson(data,true),new UTF8Encoding(false));
        }

        private static void GenerateScene()
        {
            Directory.CreateDirectory("Assets/Generated");
            var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
            var floor=GameObject.CreatePrimitive(PrimitiveType.Plane); floor.name="Floor";
            var cube=GameObject.CreatePrimitive(PrimitiveType.Cube); cube.name="PlayerCube"; cube.transform.position=new Vector3(0,0.5f,0);
            var camera=new GameObject("Main Camera").AddComponent<Camera>(); camera.tag="MainCamera";
            camera.transform.position=new Vector3(0,8,-8); camera.transform.rotation=Quaternion.Euler(45,0,0);
            camera.backgroundColor=new Color(0.08f,0.12f,0.18f); camera.clearFlags=CameraClearFlags.SolidColor;
            var light=new GameObject("Sun").AddComponent<Light>(); light.type=LightType.Directional; light.transform.rotation=Quaternion.Euler(50,-30,0);
            var runtime=new GameObject("Build Runtime").AddComponent<DemoRuntime>(); runtime.avatar=cube.transform;
            if (!EditorSceneManager.SaveScene(scene,ScenePath)) throw new Exception("Could not save generated runtime scene");
        }
    }
}
