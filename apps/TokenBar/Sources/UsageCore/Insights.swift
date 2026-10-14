import Foundation
import Darwin

public struct QuotaObservation: Codable, Sendable {
    public let provider: String
    public let windowID: String
    public let date: Date
    public let usedPercent: Double
    public let resetsAt: Date?
    public init(provider: String, windowID: String, date: Date, usedPercent: Double, resetsAt: Date?) {
        self.provider = provider; self.windowID = windowID; self.date = date
        self.usedPercent = min(100, max(0, usedPercent.isFinite ? usedPercent : 0)); self.resetsAt = resetsAt
    }
}
public struct PaceEstimate: Sendable {
    public let percentPerHour: Double
    public let hoursUntilExhausted: Double
}
public struct HistoryLedger: Sendable {
    public let url: URL
    public init(url: URL) { self.url = url }
    public func observations() throws -> [QuotaObservation] { try LedgerIO.read(QuotaObservation.self, at: url) }
    public func record(_ additions: [QuotaObservation], now: Date = Date()) throws {
        let cutoff = now.addingTimeInterval(-30 * 86400)
        let all = try observations() + additions
        var unique: [String: QuotaObservation] = [:]
        for item in all where item.date >= cutoff && item.date <= now.addingTimeInterval(60) {
            unique["\(item.provider)|\(item.windowID)|\(Int64((item.date.timeIntervalSince1970 * 1000).rounded()))"] = item
        }
        try LedgerIO.write(Array(unique.values.sorted { $0.date < $1.date }.suffix(30_000)), at: url)
    }
    public func pace(provider: String, windowID: String) throws -> PaceEstimate? {
        Self.pace(in: try observations(), provider: provider, windowID: windowID)
    }
    public static func pace(in observations: [QuotaObservation], provider: String, windowID: String) -> PaceEstimate? {
        let items = observations.filter { $0.provider == provider && $0.windowID == windowID }.sorted { $0.date < $1.date }
        guard let latest = items.last, let reset = latest.resetsAt, reset > latest.date else { return nil }
        let same = items.filter { $0.resetsAt == reset }
        // A decrease within a reset window invalidates older samples (corrections).
        var start = 0
        for index in same.indices.dropFirst() where same[index].usedPercent < same[index - 1].usedPercent { start = index }
        guard let first = same.dropFirst(start).first, latest.date.timeIntervalSince(first.date) >= 300, latest.usedPercent > first.usedPercent else { return nil }
        let pace = (latest.usedPercent - first.usedPercent) / (latest.date.timeIntervalSince(first.date) / 3600)
        return PaceEstimate(percentPerHour: pace, hoursUntilExhausted: (100 - latest.usedPercent) / pace)
    }
}

public struct QuotaAlert: Identifiable, Sendable {
    public var id: String { "\(provider).\(windowID).\(kind.rawValue)" }
    public var message: String {
        let title = provider == "codex" ? "Codex" : provider == "claude" ? "Claude" : provider.capitalized
        return kind == .reset ? "\(title) \(windowID) window has reset." : "\(title) \(windowID) window has \(Int(remainingPercent))% remaining."
    }
    public enum Kind: String, Codable, Sendable { case lowQuota, reset }
    public let kind: Kind
    public let provider: String
    public let windowID: String
    public let remainingPercent: Double
}
private struct AlertState: Codable {
    var observation: QuotaObservation
    var lowWindowKeys: [String]
}
public struct AlertEngine: Sendable {
    public let url: URL
    public init(url: URL) { self.url = url }
    public func evaluate(_ observations: [QuotaObservation], lowRemainingThreshold: Double = 20) throws -> [QuotaAlert] {
        var previous = Dictionary((try LedgerIO.read(AlertState.self, at: url)).map { ("\($0.observation.provider)|\($0.observation.windowID)", $0) }, uniquingKeysWith: { $0.observation.date > $1.observation.date ? $0 : $1 })
        let threshold = min(100, max(0, lowRemainingThreshold))
        var alerts: [QuotaAlert] = []
        for item in observations.sorted(by: { $0.date < $1.date }) {
            let key = "\(item.provider)|\(item.windowID)"
            var emitted = previous[key]?.lowWindowKeys ?? []
            let windowKey = item.resetsAt.map { String($0.timeIntervalSince1970) } ?? "unknown"
            if let old = previous[key]?.observation {
                guard item.date > old.date else { continue }
                if let oldReset = old.resetsAt, let newReset = item.resetsAt, newReset > oldReset, item.date >= oldReset, item.usedPercent < old.usedPercent {
                    alerts.append(QuotaAlert(kind: .reset, provider: item.provider, windowID: item.windowID, remainingPercent: 100 - item.usedPercent))
                } else if item.resetsAt == old.resetsAt, !emitted.contains(windowKey), 100 - old.usedPercent > threshold, 100 - item.usedPercent <= threshold {
                    emitted.append(windowKey)
                    alerts.append(QuotaAlert(kind: .lowQuota, provider: item.provider, windowID: item.windowID, remainingPercent: 100 - item.usedPercent))
                }
            }
            previous[key] = AlertState(observation: item, lowWindowKeys: Array(emitted.suffix(200)))
        }
        try LedgerIO.write(Array(previous.values), at: url)
        return alerts
    }
}

public struct UsageEvent: Codable, Identifiable, Sendable {
    public let id: String
    public let provider: String
    public let model: String
    public let timestamp: Date
    public let inputTokens: Int
    public let outputTokens: Int
    public let cachedTokens: Int
    public let estimatedCostUSD: Double?
    public let tokensPerSecond: Double?
    public init(id: String, provider: String, model: String, timestamp: Date, inputTokens: Int, outputTokens: Int, cachedTokens: Int, estimatedCostUSD: Double? = nil, tokensPerSecond: Double? = nil) {
        self.id = id; self.provider = provider; self.model = model; self.timestamp = timestamp
        self.inputTokens = max(0, inputTokens); self.outputTokens = max(0, outputTokens); self.cachedTokens = min(max(0, inputTokens), max(0, cachedTokens))
        self.estimatedCostUSD = estimatedCostUSD.flatMap { $0.isFinite && $0 >= 0 ? $0 : nil }
        self.tokensPerSecond = tokensPerSecond.flatMap { $0.isFinite && $0 >= 0 ? $0 : nil }
    }
}
public struct UsageTotals: Sendable {
    public var inputTokens = 0
    public var outputTokens = 0
    public var cachedTokens = 0
    public var eventCount = 0
    public var estimatedCostUSD: Double? = nil
    public var totalTokens: Int { inputTokens + outputTokens }
    public var pricedEventCount = 0
    mutating func add(_ event: UsageEvent) {
        inputTokens += max(0, event.inputTokens); outputTokens += max(0, event.outputTokens); cachedTokens += min(max(0, event.inputTokens), max(0, event.cachedTokens)); eventCount += 1
        if let cost = event.estimatedCostUSD, cost.isFinite, cost >= 0 { estimatedCostUSD = (estimatedCostUSD ?? 0) + cost; pricedEventCount += 1 }
    }
}
public struct DailyUsage: Identifiable, Sendable {
    public var id: Date { date }
    public let date: Date
    public let totals: UsageTotals
}
public struct UsageSummary: Sendable {
    public let today: UsageTotals
    public let month: UsageTotals
    /// Model and daily bins cover the current calendar month.
    public let byModel: [String: UsageTotals]
    public let daily: [DailyUsage]
}
public struct EventLedger: Sendable {
    public let url: URL
    public init(url: URL) { self.url = url }
    public func events() throws -> [UsageEvent] {
        var unique: [String: UsageEvent] = [:]
        for event in try LedgerIO.read(UsageEvent.self, at: url) { unique[event.id] = event }
        return unique.values.sorted { $0.timestamp < $1.timestamp }
    }
    public func append(_ additions: [UsageEvent]) throws {
        guard !additions.isEmpty else { return }
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let existing = Set(try events().map(\.id))
        var seen = existing
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let formatter = ISO8601DateFormatter(); formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        encoder.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer(); try container.encode(formatter.string(from: date))
        }
        var data = Data()
        for event in additions where seen.insert(event.id).inserted {
            data.append(try encoder.encode(event)); data.append(10)
        }
        guard !data.isEmpty else { return }
        let fd = open(url.path, O_WRONLY | O_APPEND | O_CREAT, mode_t(0o600))
        guard fd >= 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
        defer { _ = close(fd) }
        guard fchmod(fd, mode_t(0o600)) == 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
        var offset = 0
        try data.withUnsafeBytes { raw in
            guard let base = raw.baseAddress else { return }
            while offset < raw.count {
                let written = Darwin.write(fd, base.advanced(by: offset), raw.count - offset)
                guard written > 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
                offset += written
            }
        }
        if let size = (try? url.resourceValues(forKeys: [.fileSizeKey]))?.fileSize, size > 16 * 1024 * 1024 {
            var latestByID: [String: UsageEvent] = [:]
            for event in try events() { latestByID[event.id] = event }
            let recent = Array(latestByID.values.sorted { $0.timestamp < $1.timestamp }.suffix(50_000))
            try LedgerIO.write(recent, at: url)
        }
    }
    public func summary(now: Date = Date(), calendar: Calendar = .current) throws -> UsageSummary {
        var today = UsageTotals(), month = UsageTotals()
        var models: [String: UsageTotals] = [:], days: [Date: UsageTotals] = [:]
        let monthStart = calendar.dateInterval(of: .month, for: now)?.start ?? calendar.startOfDay(for: now)
        for event in try events() where event.timestamp >= monthStart && event.timestamp <= now {
            month.add(event)
            if calendar.isDate(event.timestamp, inSameDayAs: now) { today.add(event) }
            models[event.model, default: UsageTotals()].add(event)
            days[calendar.startOfDay(for: event.timestamp), default: UsageTotals()].add(event)
        }
        return UsageSummary(today: today, month: month, byModel: models, daily: days.sorted { $0.key < $1.key }.map { DailyUsage(date: $0.key, totals: $0.value) })
    }
    public func csv() throws -> String {
        let formatter = ISO8601DateFormatter()
        func quoted(_ value: String) -> String {
            // Keep exported labels literal when a spreadsheet opens the CSV.
            let safe = value.first.map { "=+-@\t\r".contains($0) } == true ? "'" + value : value
            return "\"" + safe.replacingOccurrences(of: "\"", with: "\"\"") + "\""
        }
        var rows = ["id,provider,model,timestamp,input_tokens,output_tokens,cached_tokens,estimated_cost_usd,tokens_per_second"]
        for event in try events() {
            rows.append([quoted(event.id), quoted(event.provider), quoted(event.model), quoted(formatter.string(from: event.timestamp)), String(event.inputTokens), String(event.outputTokens), String(event.cachedTokens), event.estimatedCostUSD.map { String($0) } ?? "", event.tokensPerSecond.map { String($0) } ?? ""].joined(separator: ","))
        }
        return rows.joined(separator: "\r\n") + "\r\n"
    }
}

private enum LedgerIO {
    static func read<T: Decodable>(_ type: T.Type, at url: URL) throws -> [T] {
        guard FileManager.default.fileExists(atPath: url.path) else { return [] }
        let handle = try FileHandle(forReadingFrom: url); defer { try? handle.close() }
        let size = try handle.seekToEnd(), bound: UInt64 = 32 * 1024 * 1024
        let offset = size > bound ? size - bound : 0
        try handle.seek(toOffset: offset)
        var data = try handle.read(upToCount: Int(bound)) ?? Data()
        if offset > 0 { guard let newline = data.firstIndex(of: 10) else { return [] }; data = Data(data.suffix(from: data.index(after: newline))) }
        let decoder = JSONDecoder()
        let fractional = ISO8601DateFormatter(); fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let whole = ISO8601DateFormatter()
        decoder.dateDecodingStrategy = .custom { decoder in
            let value = try decoder.singleValueContainer().decode(String.self)
            guard let date = fractional.date(from: value) ?? whole.date(from: value) else {
                throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath, debugDescription: "Invalid ISO8601 date"))
            }
            return date
        }
        return data.split(separator: 10).compactMap { try? decoder.decode(T.self, from: Data($0)) }
    }
    static func write<T: Encodable>(_ values: [T], at url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let formatter = ISO8601DateFormatter(); formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        encoder.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer(); try container.encode(formatter.string(from: date))
        }
        var data = Data()
        for value in values { data.append(try encoder.encode(value)); data.append(10) }
        let directory = url.deletingLastPathComponent()
        let temporary = directory.appendingPathComponent(".\(url.lastPathComponent).\(UUID().uuidString).tmp")
        try data.write(to: temporary, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: temporary.path)
        let result = temporary.path.withCString { source in
            url.path.withCString { destination in Darwin.rename(source, destination) }
        }
        guard result == 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
    }
}
