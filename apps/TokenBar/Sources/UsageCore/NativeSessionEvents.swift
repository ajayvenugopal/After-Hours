import Foundation
import CryptoKit

/// Imports sanitized token counters only. Recent tails are intentionally partial history;
/// neither prompts nor assistant text leave the provider's original log files.
public actor NativeSessionEvents {
    private var seen: [String: Date] = [:]
    public init() {}
    public func load() -> [UsageEvent] {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let codex = ProcessInfo.processInfo.environment["CODEX_HOME"].map { URL(fileURLWithPath: $0) } ?? home.appendingPathComponent(".codex")
        let claude = ProcessInfo.processInfo.environment["CLAUDE_CONFIG_DIR"].map { URL(fileURLWithPath: $0) } ?? home.appendingPathComponent(".claude")
        let roots = [(codex.appendingPathComponent("sessions"), true), (claude.appendingPathComponent("projects"), false)]
        let cutoff = Date().addingTimeInterval(-30 * 86400)
        var result: [UsageEvent] = []
        for (root, isCodex) in roots {
            guard let enumerator = FileManager.default.enumerator(at: root, includingPropertiesForKeys: [.contentModificationDateKey, .isRegularFileKey], options: [.skipsHiddenFiles]) else { continue }
            var files: [(URL, Date)] = [], scanned = 0
            for case let url as URL in enumerator {
                scanned += 1; if scanned > 30_000 { break }
                guard url.pathExtension == "jsonl", let values = try? url.resourceValues(forKeys: [.contentModificationDateKey, .isRegularFileKey]), values.isRegularFile == true, let modified = values.contentModificationDate, modified >= cutoff else { continue }
                files.append((url, modified))
            }
            for (url, modified) in files.sorted(by: { $0.1 > $1.1 }).prefix(100) {
                guard seen[url.path] != modified, let handle = try? FileHandle(forReadingFrom: url) else { continue }
                defer { try? handle.close() }
                guard let size = try? handle.seekToEnd() else { continue }
                let offset = size > 1_048_576 ? size - 1_048_576 : 0
                do {
                    try handle.seek(toOffset: offset)
                    var data = try handle.read(upToCount: 1_048_576) ?? Data()
                    if offset > 0 {
                        guard let newline = data.firstIndex(of: 10) else { continue }
                        data = Data(data.suffix(from: data.index(after: newline)))
                    }
                    let parsed = isCodex ? Self.parseCodexLines(data, sessionID: url.path) : Self.parseClaudeLines(data, sessionID: url.path)
                    result.append(contentsOf: parsed.filter { $0.timestamp >= cutoff })
                    seen[url.path] = modified
                } catch { continue }
            }
        }
        return result
    }
    public static func parseCodexLines(_ data: Data, sessionID: String) -> [UsageEvent] {
        var events: [String: UsageEvent] = [:], model = "Codex (unknown model)"
        let dateParser = timestampParser()
        for root in objects(data) {
            if root["type"] as? String == "turn_context", let payload = root["payload"] as? [String: Any], let value = payload["model"] as? String { model = value }
            guard root["type"] as? String == "event_msg", let payload = root["payload"] as? [String: Any], payload["type"] as? String == "token_count", let info = payload["info"] as? [String: Any], let last = info["last_token_usage"] as? [String: Any], let total = info["total_token_usage"] as? [String: Any], let cumulative = count(total["total_tokens"]), cumulative > 0, let date = dateParser(root["timestamp"]), let input = count(last["input_tokens"]), let output = count(last["output_tokens"]), input > 0 || output > 0 else { continue }
            let id = digest("codex|\(sessionID)|\(cumulative)")
            // rate-only repeats carry identical counters; retain the first timestamp.
            guard events[id] == nil else { continue }
            let cache = min(input, count(last["cached_input_tokens"]) ?? 0)
            events[id] = UsageEvent(id: id, provider: "codex", model: model, timestamp: date, inputTokens: input, outputTokens: output, cachedTokens: cache)
        }
        return events.values.sorted { $0.timestamp < $1.timestamp }
    }
    public static func parseClaudeLines(_ data: Data, sessionID: String) -> [UsageEvent] {
        var events: [String: UsageEvent] = [:]
        let dateParser = timestampParser()
        for root in objects(data) {
            guard root["type"] as? String == "assistant", let message = root["message"] as? [String: Any], let messageID = message["id"] as? String, !messageID.isEmpty, let usage = message["usage"] as? [String: Any], let input = count(usage["input_tokens"]), let output = count(usage["output_tokens"]), let date = dateParser(root["timestamp"]) else { continue }
            let cache = count(usage["cache_read_input_tokens"]) ?? 0
            let creation = count(usage["cache_creation_input_tokens"]) ?? 0
            let (part, overflow1) = input.addingReportingOverflow(cache), (all, overflow2) = part.addingReportingOverflow(creation)
            guard !overflow1, !overflow2, all > 0 || output > 0 else { continue }
            let id = digest("claude|\(sessionID)|\(messageID)")
            // Streaming snapshots overwrite earlier records for the same message.
            events[id] = UsageEvent(id: id, provider: "claude", model: message["model"] as? String ?? "Claude (unknown model)", timestamp: date, inputTokens: all, outputTokens: output, cachedTokens: cache)
        }
        return events.values.sorted { $0.timestamp < $1.timestamp }
    }
    private static func timestampParser() -> (Any?) -> Date? {
        let fractional = ISO8601DateFormatter(); fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let whole = ISO8601DateFormatter()
        return { value in
            if let seconds = UsageParser.number(value), seconds > 0 { return Date(timeIntervalSince1970: seconds) }
            guard let text = value as? String else { return nil }
            return fractional.date(from: text) ?? whole.date(from: text)
        }
    }
    private static func objects(_ data: Data) -> [[String: Any]] {
        data.split(separator: 10).compactMap { try? JSONSerialization.jsonObject(with: Data($0)) as? [String: Any] }
    }
    private static func count(_ value: Any?) -> Int? {
        guard let number = UsageParser.number(value), number >= 0, number < Double(Int.max), number.rounded(.towardZero) == number else { return nil }
        return Int(number)
    }
    private static func digest(_ text: String) -> String { SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined() }
}
