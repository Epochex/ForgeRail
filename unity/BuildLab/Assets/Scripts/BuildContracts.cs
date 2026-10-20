using System;
using System.IO;
using System.Security.Cryptography;
using System.Text.RegularExpressions;

namespace GameBuild
{
    [Serializable]
    public sealed class BuildRequest
    {
        public string build_id;
        public string commit_sha;
        public string input_digest;
        public string output_dir;
        public string target;
        public string configuration;
    }

    [Serializable]
    public class BuildInfo
    {
        public string adapter = "unity";
        public string build_id;
        public string commit_sha;
        public string input_digest;
        public string target;
        public string configuration;
        public string unity_version;
        public string config_sha256;
        public string bundle_sha256;
    }

    [Serializable]
    public sealed class SmokeReceipt : BuildInfo
    {
        public bool asset_loaded;
        public string status;
        public string error;
        public string started_at;
    }

    public static class BuildContracts
    {
        public static void ValidateRequest(BuildRequest request, string projectDirectory)
        {
            if (request == null) throw new ArgumentException("Build request is required");
            if (!Regex.IsMatch(request.build_id ?? "", @"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"))
                throw new ArgumentException("build_id must be a safe identifier");
            if (!Regex.IsMatch(request.commit_sha ?? "", @"^[0-9a-f]{40}$"))
                throw new ArgumentException("commit_sha must be a full lowercase Git SHA");
            if (!Regex.IsMatch(request.input_digest ?? "", @"^[0-9a-f]{64}$"))
                throw new ArgumentException("input_digest must be lowercase SHA256");
            if (request.target != "StandaloneWindows64" && request.target != "Windows64")
                throw new ArgumentException("Only Windows x64 Mono is supported");
            if (request.configuration != "Release" && request.configuration != "Debug" && request.configuration != "Development")
                throw new ArgumentException("configuration must be Release, Debug or Development");
            if (string.IsNullOrWhiteSpace(request.output_dir) || !Path.IsPathRooted(request.output_dir))
                throw new ArgumentException("output_dir must be absolute");
            var output = Path.GetFullPath(request.output_dir).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var project = Path.GetFullPath(projectDirectory).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            if (output.Length == 0 || output == Path.GetPathRoot(output).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) ||
                output.Equals(project,StringComparison.OrdinalIgnoreCase) ||
                output.StartsWith(project + Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase) ||
                project.StartsWith(output + Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("output_dir must be outside and not an ancestor of the Unity project");
        }

        public static string Sha256(byte[] bytes)
        {
            using (var sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        }

        public static bool ReceiptMatches(BuildRequest request, SmokeReceipt receipt)
        {
            return receipt != null && receipt.asset_loaded && receipt.build_id == request.build_id &&
                receipt.commit_sha == request.commit_sha && receipt.input_digest == request.input_digest;
        }
    }
}
