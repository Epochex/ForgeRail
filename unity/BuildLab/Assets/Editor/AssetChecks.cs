using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace GameBuild
{
    [Serializable]
    public sealed class AssetIssue
    {
        public string rule_id;
        public string path;
        public string message;
        public AssetIssue(string rule, string asset, string reason) { rule_id=rule; path=asset; message=reason; }
    }

    public static class AssetChecks
    {
        public const string ConfigurationAsset = "Assets/BundleSource/demo-config.json";

        public static List<AssetIssue> ValidateAssets()
        {
            var issues = new List<AssetIssue>();
            var config = AssetDatabase.LoadAssetAtPath<TextAsset>(ConfigurationAsset);
            if (config == null) issues.Add(new AssetIssue("unity.required_asset",ConfigurationAsset,"Required bundle config is missing or not imported"));
            else
            {
                try
                {
                    var data = JsonUtility.FromJson<DemoConfiguration>(config.text);
                    if (data == null || data.move_speed <= 0 || string.IsNullOrWhiteSpace(data.resource_version))
                        throw new ArgumentException("move_speed must be positive and resource_version nonempty");
                }
                catch (Exception error) { issues.Add(new AssetIssue("unity.config",ConfigurationAsset,error.Message)); }
            }
            foreach (var path in AssetDatabase.GetAllAssetPaths())
            {
                if (!path.StartsWith("Assets/",StringComparison.Ordinal) || AssetDatabase.IsValidFolder(path)) continue;
                var importer = AssetImporter.GetAtPath(path) as TextureImporter;
                if (importer != null && (importer.maxTextureSize > 2048 || importer.isReadable))
                    issues.Add(new AssetIssue("unity.texture_import",path,"Textures require maxTextureSize <= 2048 and Read/Write disabled"));
                if (path.EndsWith(".prefab",StringComparison.OrdinalIgnoreCase))
                {
                    GameObject contents = null;
                    try { contents = PrefabUtility.LoadPrefabContents(path); InspectHierarchy(contents,path,issues); }
                    catch (Exception error) { issues.Add(new AssetIssue("unity.prefab",path,error.Message)); }
                    finally { if (contents != null) PrefabUtility.UnloadPrefabContents(contents); }
                }
                if (path.EndsWith(".unity",StringComparison.OrdinalIgnoreCase))
                {
                    var existing = SceneManager.GetSceneByPath(path);
                    var opened = !existing.IsValid() || !existing.isLoaded;
                    Scene scene = default(Scene);
                    try
                    {
                        scene = opened ? EditorSceneManager.OpenScene(path,OpenSceneMode.Additive) : existing;
                        foreach (var root in scene.GetRootGameObjects()) InspectHierarchy(root,path,issues);
                    }
                    catch (Exception error) { issues.Add(new AssetIssue("unity.scene",path,error.Message)); }
                    finally { if (opened && scene.IsValid()) EditorSceneManager.CloseScene(scene,true); }
                }
            }
            return issues;
        }

        private static void InspectHierarchy(GameObject root, string path, List<AssetIssue> issues)
        {
            foreach (var transform in root.GetComponentsInChildren<Transform>(true))
            {
                if (GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(transform.gameObject) > 0)
                    issues.Add(new AssetIssue("unity.missing_script",path,"Missing Script on " + transform.name));
                foreach (var component in transform.GetComponents<Component>())
                {
                    if (component == null) continue;
                    using (var serialized = new SerializedObject(component))
                    {
                        var property = serialized.GetIterator();
                        while (property.NextVisible(true))
                            if (property.propertyType == SerializedPropertyType.ObjectReference &&
                                property.objectReferenceValue == null && property.objectReferenceInstanceIDValue != 0)
                                issues.Add(new AssetIssue("unity.missing_reference",path,transform.name + ": " + property.propertyPath));
                    }
                }
            }
        }
    }
}
