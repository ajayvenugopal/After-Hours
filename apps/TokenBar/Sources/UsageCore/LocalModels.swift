import Foundation

public struct LocalModel: Identifiable, Sendable {
    public let id: String
    public let name: String
    public let memoryBytes: Double?
    public let contextLength: Int?
    public init(id: String, name: String, memoryBytes: Double? = nil, contextLength: Int? = nil) {
        self.id = id; self.name = name; self.memoryBytes = memoryBytes; self.contextLength = contextLength
    }
}
public struct LocalServer: Identifiable, Sendable {
    public let id: String
    public let title: String
    public let online: Bool
    public let models: [LocalModel]
    public let message: String?
    public init(id: String, title: String, online: Bool, models: [LocalModel] = [], message: String? = nil) {
        self.id = id; self.title = title; self.online = online; self.models = models; self.message = message
    }
}
public enum LocalModels {
    public static func load(id: String) async -> LocalServer {
        let title = id == "ollama" ? "Ollama" : "LM Studio"
        let path = id == "ollama" ? "http://127.0.0.1:11434/api/ps" : "http://127.0.0.1:1234/api/v1/models"
        var request = URLRequest(url: URL(string: path)!); request.timeoutInterval = 3
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200, data.count < 2_000_000 else {
                return LocalServer(id: id, title: title, online: false, message: "Server requires authentication or returned an error.")
            }
            return try parse(id: id, data: data)
        } catch {
            return LocalServer(id: id, title: title, online: false, message: "Start the local server to see loaded models.")
        }
    }
    public static func parse(id: String, data: Data) throws -> LocalServer {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any], let rows = root["models"] as? [[String: Any]] else { throw UsageParser.ParseError.invalid }
        var models: [LocalModel] = []
        for row in rows {
            if id == "ollama", let name = row["name"] as? String {
                models.append(LocalModel(id: name, name: name, memoryBytes: UsageParser.number(row["size_vram"]), contextLength: positiveInt(row["context_length"])))
            } else if let instances = row["loaded_instances"] as? [[String: Any]] {
                for instance in instances {
                    let key = instance["id"] as? String ?? row["key"] as? String ?? "model"
                    let config = instance["config"] as? [String: Any] ?? [:]
                    models.append(LocalModel(id: key, name: row["display_name"] as? String ?? key, contextLength: positiveInt(config["context_length"])))
                }
            }
        }
        return LocalServer(id: id, title: id == "ollama" ? "Ollama" : "LM Studio", online: true, models: models)
    }
    private static func positiveInt(_ value: Any?) -> Int? {
        guard let n = UsageParser.number(value), n > 0, n < Double(Int.max) else { return nil }
        return Int(n)
    }
}
