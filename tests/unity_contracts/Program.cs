using System;
using System.IO;
using GameBuild;

internal static class Program
{
    static int checks;
    static void Require(bool condition, string name) { if (!condition) throw new Exception(name); checks++; }
    static void Reject(Action action, string name)
    {
        try { action(); } catch (ArgumentException) { checks++; return; }
        throw new Exception("Expected rejection: " + name);
    }
    static BuildRequest Good() => new BuildRequest {
        build_id = "20261020-abcd1234-one", commit_sha = new string('a',40),
        input_digest = new string('b',64), output_dir = Path.Combine(Path.GetTempPath(),"gamebuild-output"),
        target = "StandaloneWindows64", configuration = "Release"
    };
    static int Main()
    {
        var request = Good();
        var project = Path.Combine(Path.GetTempPath(), "gamebuild-project");
        BuildContracts.ValidateRequest(request, project);
        Require(BuildContracts.Sha256(System.Text.Encoding.UTF8.GetBytes("abc")) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "known SHA256");
        request.commit_sha = "abcd1234"; Reject(() => BuildContracts.ValidateRequest(request,project), "short commit");
        request = Good(); request.input_digest = new string('z',64); Reject(() => BuildContracts.ValidateRequest(request,project), "nonhex digest");
        request = Good(); request.output_dir = project; Reject(() => BuildContracts.ValidateRequest(request,project), "project overwrite");
        request.output_dir = Path.Combine(project,"Assets","Generated"); Reject(() => BuildContracts.ValidateRequest(request,project), "source subtree overwrite");
        request = Good(); request.output_dir = Path.GetPathRoot(project); Reject(() => BuildContracts.ValidateRequest(request,project), "root overwrite");
        request = Good(); request.target = "Android"; Reject(() => BuildContracts.ValidateRequest(request,project), "unsupported target");
        request = Good(); request.configuration = "unknown"; Reject(() => BuildContracts.ValidateRequest(request,project), "unknown configuration");
        request = Good(); request.build_id = "../escape"; Reject(() => BuildContracts.ValidateRequest(request,project), "unsafe build id");
        request = Good(); var receipt = new SmokeReceipt { build_id=request.build_id, commit_sha=request.commit_sha, input_digest=request.input_digest, asset_loaded=true };
        Require(BuildContracts.ReceiptMatches(request,receipt), "matching receipt");
        receipt.asset_loaded=false; Require(!BuildContracts.ReceiptMatches(request,receipt), "must actually load bundle");
        receipt.asset_loaded=true; receipt.commit_sha=new string('c',40); Require(!BuildContracts.ReceiptMatches(request,receipt), "reject stale Player identity");
        var temporary=Path.Combine(Path.GetTempPath(),"gamebuild-cache-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temporary);
        try
        {
            var cache=Path.Combine(temporary,"cache"); var source=Path.Combine(temporary,"source");
            Directory.CreateDirectory(source); File.WriteAllText(Path.Combine(source,"demo"),"first bundle");
            var key=new string('a',64);
            Require(!BundleCache.TryRestore(cache,key,Path.Combine(temporary,"miss")), "cache miss");
            Require(BundleCache.Publish(cache,key,source), "publish cache");
            Require(BundleCache.TryRestore(cache,key,Path.Combine(temporary,"hit")), "verified cache hit");
            Require(File.ReadAllText(Path.Combine(temporary,"hit","demo")) == "first bundle", "restored bytes");
            File.WriteAllText(Path.Combine(source,"demo"),"second bundle"); BundleCache.Publish(cache,key,source);
            Require(BundleCache.TryRestore(cache,key,Path.Combine(temporary,"immutable")), "existing cache remains valid");
            Require(File.ReadAllText(Path.Combine(temporary,"immutable","demo")) == "first bundle", "cache cannot be overwritten");
            File.WriteAllText(Path.Combine(cache,key,"demo"),"tampered");
            Require(!BundleCache.TryRestore(cache,key,Path.Combine(temporary,"corrupt")), "cache corruption is a miss");
            Require(!Directory.Exists(Path.Combine(cache,key)), "corrupt cache quarantined");
            Require(BundleCache.Publish(cache,key,source), "rebuild after corruption");
            File.AppendAllText(Path.Combine(cache,key,"cache-index.tsv"),"../escape\t1\t" + new string('b',64) + "\n");
            Require(!BundleCache.TryRestore(cache,key,Path.Combine(temporary,"hostile")), "cache path traversal rejected");
        }
        finally { Directory.Delete(temporary,true); }
        Console.WriteLine("PASS " + checks + " executable C# contract checks (not Unity engine compilation)");
        return 0;
    }
}
