using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace GameBuild
{
    // Executed by the real Editor; no NUnit/package dependency or simulated Unity types.
    public static class EditorAcceptance
    {
        public static void Run()
        {
            var output = BuildEntry.Argument("-acceptanceOutput");
            if (string.IsNullOrEmpty(output)) throw new ArgumentException("-acceptanceOutput is required");
            const string directory = "Assets/__GameBuildAcceptance";
            var passed = false;
            try
            {
                AssetDatabase.CreateFolder("Assets", "__GameBuildAcceptance");
                var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
                var go = new GameObject("MissingScriptFixture");
                go.AddComponent<DemoRuntime>();
                var path = directory + "/Missing.prefab";
                PrefabUtility.SaveAsPrefabAsset(go,path);
                UnityEngine.Object.DestroyImmediate(go);
                var text = File.ReadAllText(path);
                var guid = AssetDatabase.AssetPathToGUID("Assets/Scripts/DemoRuntime.cs");
                if (string.IsNullOrEmpty(guid)) throw new Exception("Runtime script was not imported");
                File.WriteAllText(path,text.Replace(guid,"00000000000000000000000000000001"));
                AssetDatabase.ImportAsset(path,ImportAssetOptions.ForceSynchronousImport);
                if (!AssetChecks.ValidateAssets().Any(x=>x.rule_id == "unity.missing_script" && x.path == path))
                    throw new Exception("Missing Script fixture was accepted");
                AssetDatabase.DeleteAsset(path);
                var texture = new Texture2D(4,4);
                var texturePath = directory + "/TooLarge.png";
                File.WriteAllBytes(texturePath,texture.EncodeToPNG());
                UnityEngine.Object.DestroyImmediate(texture);
                AssetDatabase.ImportAsset(texturePath,ImportAssetOptions.ForceSynchronousImport);
                var importer = (TextureImporter)AssetImporter.GetAtPath(texturePath);
                importer.maxTextureSize = 8192;
                importer.SaveAndReimport();
                if (!AssetChecks.ValidateAssets().Any(x=>x.rule_id == "unity.texture_import" && x.path == texturePath))
                    throw new Exception("Illegal texture import setting was accepted");
                AssetDatabase.DeleteAsset(texturePath);
                if (AssetChecks.ValidateAssets().Count != 0) throw new Exception("Clean project was rejected");
                passed = true;
                Debug.Log("GAMEBUILD_EDITOR_ACCEPTANCE_PASS: missing script, importer, clean project");
            }
            finally
            {
                EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
                AssetDatabase.DeleteAsset(directory);
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output)));
                File.WriteAllText(output,"{\"status\":\"" + (passed ? "passed" : "failed") + "\",\"engine_tests\":3,\"unity_version\":\"" + Application.unityVersion + "\"}");
            }
            if (!passed) throw new Exception("Editor acceptance failed");
        }
    }
}
