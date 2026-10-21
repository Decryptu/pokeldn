using System.Reflection;
using System.Text.Json.Nodes;

// Structured application diagnostics. PKHeX's own reports remain opaque provider text.
static class LocalizedError
{
    static readonly Dictionary<string, string> English = Load();

    static Dictionary<string, string> Load()
    {
        using var source = Assembly.GetExecutingAssembly().GetManifestResourceStream("pokeldn.messages.en.json")!;
        return JsonNode.Parse(source)!.AsObject().ToDictionary(pair => pair.Key, pair => pair.Value!.GetValue<string>());
    }

    internal static Exception Make(string key, JsonObject parameters, Func<string, Exception> create)
    {
        var text = English[key];
        foreach (var (name, value) in parameters)
            text = text.Replace("{" + name + "}", value is JsonValue v && v.TryGetValue<string>(out var s)
                ? s : value?.ToJsonString() ?? "");
        var exception = create(text);
        exception.Data["localization"] = new JsonObject { ["$message"] = key, ["params"] = parameters };
        return exception;
    }
}
