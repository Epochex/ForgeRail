using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace GameBuild
{
    // Engine-independent immutable export cache. All entries verify content before reuse.
    public static class BundleCache
    {
        private const string Index = "cache-index.tsv";

        public static bool TryRestore(string root, string key, string destination)
        {
            var entry = Entry(root,key);
            if (!Directory.Exists(entry)) return false;
            if (Directory.Exists(destination) && Directory.EnumerateFileSystemEntries(destination).Any())
                throw new ArgumentException("Cache destination must be empty");
            var staging=Path.GetFullPath(destination) + ".restore-" + Guid.NewGuid().ToString("N");
            try
            {
                var index=Path.Combine(entry,Index);
                if (!File.Exists(index) || (File.GetAttributes(index) & FileAttributes.ReparsePoint) != 0)
                { Quarantine(root,key,entry); return false; }
                var lines=File.ReadAllLines(index,Encoding.UTF8);
                if (!Valid(entry,lines)) { Quarantine(root,key,entry); return false; }
                Copy(entry,staging);
                // Revalidate copied bytes against the same manifest, closing validation/copy races.
                if (!Valid(staging,lines)) { Quarantine(root,key,entry); return false; }
                if (Directory.Exists(destination)) Directory.Delete(destination,false);
                Directory.Move(staging,destination);
                return true;
            }
            catch (IOException) { Quarantine(root,key,entry); return false; }
            finally { if (Directory.Exists(staging)) Directory.Delete(staging,true); }
        }

        public static bool Publish(string root, string key, string source)
        {
            var entry=Entry(root,key);
            Directory.CreateDirectory(root);
            if (Directory.Exists(entry))
            {
                if (Valid(entry)) return true;
                Quarantine(root,key,entry);
            }
            var staging=Path.Combine(Path.GetFullPath(root),".staging-" + Guid.NewGuid().ToString("N"));
            try
            {
                Copy(source,staging);
                var lines=Files(staging).Select(path=> {
                    var relative=Relative(staging,path);
                    if (relative.IndexOfAny(new[]{'\t','\r','\n'}) >= 0) throw new ArgumentException("Invalid cache filename");
                    return relative + "\t" + new FileInfo(path).Length.ToString(CultureInfo.InvariantCulture) + "\t" + BuildContracts.Sha256(File.ReadAllBytes(path));
                }).ToArray();
                if (lines.Length == 0) throw new ArgumentException("Cannot cache an empty export");
                File.WriteAllLines(Path.Combine(staging,Index),lines,new UTF8Encoding(false));
                if (!Valid(staging)) throw new IOException("Cache staging validation failed");
                try { Directory.Move(staging,entry); }
                catch (IOException) { if (!Valid(entry)) throw; }
                return true;
            }
            finally { if (Directory.Exists(staging)) Directory.Delete(staging,true); }
        }

        private static string Entry(string root,string key)
        {
            if (!Regex.IsMatch(key ?? "", "^[a-f0-9]{64}$")) throw new ArgumentException("Cache key must be lowercase SHA256");
            return Path.Combine(Path.GetFullPath(root),key);
        }

        private static string[] Files(string directory)
        {
            var result=new List<string>();
            Collect(directory,directory,result);
            return result.OrderBy(x=>x,StringComparer.Ordinal).ToArray();
        }

        private static void Collect(string directory,string root,List<string> result)
        {
            if ((File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0) throw new IOException("Cache links are forbidden");
            foreach (var item in Directory.EnumerateFileSystemEntries(directory))
            {
                var attributes=File.GetAttributes(item);
                if ((attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("Cache links are forbidden");
                if ((attributes & FileAttributes.Directory) != 0) Collect(item,root,result);
                else if (item != Path.Combine(root,Index)) result.Add(item);
            }
        }

        private static string Relative(string directory,string file)
        {
            return file.Substring(directory.TrimEnd(Path.DirectorySeparatorChar,Path.AltDirectorySeparatorChar).Length + 1).Replace('\\','/');
        }

        private static bool Valid(string entry,string[] fixedLines=null)
        {
            try
            {
                if (!Directory.Exists(entry)) return false;
                var actual=Files(entry).Select(path=>Relative(entry,path)).ToArray();
                var index=Path.Combine(entry,Index);
                if (fixedLines == null && (!File.Exists(index) || (File.GetAttributes(index) & FileAttributes.ReparsePoint) != 0)) return false;
                if (File.Exists(index) && (File.GetAttributes(index) & FileAttributes.ReparsePoint) != 0) return false;
                var expected=new HashSet<string>(StringComparer.Ordinal);
                foreach (var line in fixedLines ?? File.ReadAllLines(index,Encoding.UTF8))
                {
                    var parts=line.Split('\t');
                    long size;
                    if (parts.Length != 3 || !long.TryParse(parts[1],NumberStyles.None,CultureInfo.InvariantCulture,out size) || size < 0 ||
                        !Regex.IsMatch(parts[2],"^[a-f0-9]{64}$")) return false;
                    var relative=parts[0];
                    if (relative.Length == 0 || Path.IsPathRooted(relative) || relative.Contains("\\") || relative.Contains(":") ||
                        relative.Split('/').Any(x=>x.Length == 0 || x == "." || x == "..") || relative == Index || !expected.Add(relative)) return false;
                    var file=Path.Combine(entry,relative);
                    if (!File.Exists(file) || new FileInfo(file).Length != size || BuildContracts.Sha256(File.ReadAllBytes(file)) != parts[2]) return false;
                }
                return expected.Count > 0 && expected.SetEquals(actual);
            }
            catch (IOException) { return false; }
            catch (UnauthorizedAccessException) { return false; }
            catch (ArgumentException) { return false; }
        }

        private static void Copy(string source,string destination)
        {
            Directory.CreateDirectory(destination);
            foreach (var file in Files(source))
            {
                var target=Path.Combine(destination,Relative(source,file));
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                File.Copy(file,target,false);
            }
        }

        private static void Quarantine(string root,string key,string entry)
        {
            try { Directory.Move(entry,Path.Combine(Path.GetFullPath(root),key + ".corrupt-" + Guid.NewGuid().ToString("N"))); }
            catch (IOException) { /* Another reader may already have isolated the entry. */ }
        }
    }
}
