using Newtonsoft.Json;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;

namespace BIMaestro.Localization
{
    /// <summary>
    /// A community translation loaded from a JSON file.
    /// French and English stay built into the code; every other language is a pack.
    /// </summary>
    public sealed class LanguagePack
    {
        internal LanguagePack(string code, string name, string culture, IEnumerable<string> revitLanguages)
        {
            Code = code;
            Name = string.IsNullOrWhiteSpace(name) ? code : name.Trim();
            Culture = culture;
            RevitLanguages = new HashSet<string>(revitLanguages ?? Enumerable.Empty<string>(), StringComparer.OrdinalIgnoreCase);
        }

        /// <summary>Language code, e.g. "de". Also used as the saved preference.</summary>
        public string Code { get; }

        /// <summary>Name shown in the language list, e.g. "Deutsch".</summary>
        public string Name { get; private set; }

        /// <summary>Culture used for dates and numbers, e.g. "de-DE". Optional.</summary>
        public string Culture { get; private set; }

        /// <summary>Values of Revit's LanguageType (e.g. "German") that select this pack in Automatic mode.</summary>
        public HashSet<string> RevitLanguages { get; }

        /// <summary>Keys are the English or French source text, values the translation.</summary>
        internal Dictionary<string, string> Strings { get; } = new Dictionary<string, string>(StringComparer.Ordinal);

        internal List<string> Files { get; } = new List<string>();

        internal void Merge(LanguagePackFile file, string path)
        {
            if (!string.IsNullOrWhiteSpace(file.Name)) Name = file.Name.Trim();
            if (!string.IsNullOrWhiteSpace(file.Culture)) Culture = file.Culture.Trim();
            if (file.RevitLanguages != null)
                foreach (string revitLanguage in file.RevitLanguages)
                    if (!string.IsNullOrWhiteSpace(revitLanguage)) RevitLanguages.Add(revitLanguage.Trim());

            if (file.Strings != null)
            {
                foreach (var pair in file.Strings)
                {
                    // Empty values mean "not translated yet": the English text is used instead.
                    if (string.IsNullOrEmpty(pair.Key) || string.IsNullOrWhiteSpace(pair.Value)) continue;
                    Strings[pair.Key] = pair.Value;
                }
            }

            Files.Add(path);
        }

        internal bool TryTranslate(string source, out string translation)
        {
            translation = null;
            return !string.IsNullOrEmpty(source) && Strings.TryGetValue(source, out translation);
        }
    }

    /// <summary>JSON shape of a file in Content\Languages or in the user's Languages preference folder.</summary>
    internal sealed class LanguagePackFile
    {
        [JsonProperty("code")] public string Code { get; set; }
        [JsonProperty("name")] public string Name { get; set; }
        [JsonProperty("culture")] public string Culture { get; set; }
        [JsonProperty("revitLanguages")] public List<string> RevitLanguages { get; set; }
        [JsonProperty("strings")] public Dictionary<string, string> Strings { get; set; }
    }

    /// <summary>
    /// Loads language packs once. Packs shipped next to BIMaestro.dll (Content\Languages)
    /// are read first, then the user's own folder
    /// (Documents\BIMaestro_Revit\SauvegardePréférence\Languages), whose entries win.
    /// A broken file is skipped: a translation must never prevent BIMaestro from starting.
    /// </summary>
    public static class LanguagePacks
    {
        public const string FolderName = "Languages";

        private static readonly object Sync = new object();
        private static Dictionary<string, LanguagePack> _packs;

        public static IReadOnlyList<LanguagePack> All
        {
            get
            {
                return Load().Values
                    .OrderBy(pack => pack.Name, StringComparer.CurrentCultureIgnoreCase)
                    .ToList();
            }
        }

        public static bool TryGet(string code, out LanguagePack pack)
        {
            pack = null;
            return !string.IsNullOrWhiteSpace(code) && Load().TryGetValue(code.Trim(), out pack);
        }

        public static LanguagePack FindByRevitLanguage(string revitLanguage)
        {
            if (string.IsNullOrWhiteSpace(revitLanguage)) return null;
            return All.FirstOrDefault(pack => pack.RevitLanguages.Contains(revitLanguage.Trim()));
        }

        /// <summary>Forgets the loaded packs so the next access reads the files again.</summary>
        public static void Reload()
        {
            lock (Sync) _packs = null;
        }

        public static IEnumerable<string> SearchFolders()
        {
            string shipped = null;
            try
            {
                string assemblyFolder = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
                if (!string.IsNullOrEmpty(assemblyFolder))
                    shipped = Path.Combine(assemblyFolder, "Content", FolderName);
            }
            catch (Exception ex)
            {
                Log("Unable to locate the shipped language folder", ex);
            }
            if (shipped != null) yield return shipped;

            string user = null;
            try
            {
                user = global::BIMaestro.Storage.PreferenceStorage.Folder(FolderName);
            }
            catch (Exception ex)
            {
                Log("Unable to locate the user language folder", ex);
            }
            if (user != null) yield return user;
        }

        private static Dictionary<string, LanguagePack> Load()
        {
            var packs = _packs;
            if (packs != null) return packs;

            lock (Sync)
            {
                if (_packs != null) return _packs;

                packs = new Dictionary<string, LanguagePack>(StringComparer.OrdinalIgnoreCase);
                foreach (string folder in SearchFolders())
                {
                    string[] files;
                    try
                    {
                        if (!Directory.Exists(folder)) continue;
                        files = Directory.GetFiles(folder, "*.json");
                        Array.Sort(files, StringComparer.OrdinalIgnoreCase);
                    }
                    catch (Exception ex)
                    {
                        Log($"Unable to list '{folder}'", ex);
                        continue;
                    }

                    foreach (string path in files)
                        LoadFile(path, packs);
                }

                _packs = packs;
                return packs;
            }
        }

        private static void LoadFile(string path, Dictionary<string, LanguagePack> packs)
        {
            // Files starting with "_" (e.g. _template.json) are documentation, not languages.
            if (Path.GetFileName(path).StartsWith("_", StringComparison.Ordinal)) return;

            try
            {
                var file = JsonConvert.DeserializeObject<LanguagePackFile>(File.ReadAllText(path));
                string code = file?.Code?.Trim();
                if (string.IsNullOrEmpty(code))
                    code = Path.GetFileNameWithoutExtension(path);

                if (UiLanguage.IsBuiltInCode(code))
                {
                    Log($"'{path}' uses the reserved code '{code}' and was ignored", null);
                    return;
                }

                if (!string.IsNullOrWhiteSpace(file?.Culture) && !IsValidCulture(file.Culture))
                {
                    Log($"'{path}' has an unknown culture '{file.Culture}', it was ignored", null);
                    file.Culture = null;
                }

                if (!packs.TryGetValue(code, out LanguagePack pack))
                {
                    pack = new LanguagePack(code, null, null, null);
                    packs[code] = pack;
                }
                pack.Merge(file ?? new LanguagePackFile(), path);
            }
            catch (Exception ex)
            {
                Log($"Unable to read language file '{path}'", ex);
            }
        }

        private static bool IsValidCulture(string name)
        {
            try
            {
                CultureInfo.GetCultureInfo(name.Trim());
                return true;
            }
            catch (CultureNotFoundException)
            {
                return false;
            }
        }

        private static void Log(string message, Exception ex)
        {
            Debug.WriteLine(ex == null
                ? $"[LanguagePacks] {message}"
                : $"[LanguagePacks] {message}: {ex}");
        }
    }
}
