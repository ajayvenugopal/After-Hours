import Foundation

public enum UsageProvider: String, CaseIterable, Sendable {
    case codex, claude
    public var title: String { self == .codex ? "Codex" : "Claude" }
}

public struct UsageWindow: Identifiable, Sendable {
    public let id: String
    public let title: String
    public let usedPercent: Double
    public let resetsAt: Date?
    public let durationMinutes: Int?
    public var remainingPercent: Double { 100 - usedPercent }
    public init(id: String, title: String, usedPercent: Double, resetsAt: Date? = nil, durationMinutes: Int? = nil) {
        self.id = id; self.title = title
        self.usedPercent = usedPercent.isFinite ? min(100, max(0, usedPercent)) : 0
        self.resetsAt = resetsAt; self.durationMinutes = durationMinutes
    }
}

public struct ProviderSnapshot: Sendable {
    public let provider: UsageProvider
    public let windows: [UsageWindow]
    public let updatedAt: Date?
    public let source: String
    public let message: String?
    /// Context capacity left, not a subscription token allowance.
    public let contextRemainingTokens: Int?
    public init(provider: UsageProvider, windows: [UsageWindow] = [], updatedAt: Date? = nil, source: String = "Not connected", message: String? = nil, contextRemainingTokens: Int? = nil) {
        self.provider = provider; self.windows = windows; self.updatedAt = updatedAt
        self.source = source; self.message = message; self.contextRemainingTokens = contextRemainingTokens
    }
}

public enum UsageParser {
    static func number(_ value: Any?) -> Double? {
        guard let n = value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue.isFinite else { return nil }
        return n.doubleValue
    }
    static func date(_ value: Any?) -> Date? {
        if let seconds = number(value), seconds > 0 { return Date(timeIntervalSince1970: seconds) }
        guard let text = value as? String else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: text) ?? ISO8601DateFormatter().date(from: text)
    }
    static func window(_ object: Any?, id: String, title: String, camel: Bool) -> UsageWindow? {
        guard let obj = object as? [String: Any], let used = number(obj[camel ? "usedPercent" : "used_percent"] ?? obj["used_percentage"]) else { return nil }
        let duration = number(obj[camel ? "windowDurationMins" : "window_minutes"]).flatMap { $0 > 0 && $0 < Double(Int.max) ? Int($0) : nil }
        let label = duration == 300 ? "5-hour window" : duration == 10080 ? "Weekly window" : title
        return UsageWindow(id: id, title: label, usedPercent: used, resetsAt: date(obj[camel ? "resetsAt" : "resets_at"] ?? obj["reset_at"]), durationMinutes: duration)
    }
    public static func codexRPC(_ data: Data, now: Date = Date()) throws -> ProviderSnapshot {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw ParseError.invalid }
        let result = root["result"] as? [String: Any] ?? root
        var limits = result["rateLimits"] as? [String: Any]
        if limits == nil, let grouped = result["rateLimitsByLimitId"] as? [String: [String: Any]] {
            limits = grouped["codex"] ?? grouped.sorted(by: { $0.key < $1.key }).first?.value
        }
        guard let limits else { throw ParseError.missingLimits }
        let windows = [window(limits["primary"], id: "primary", title: "Primary window", camel: true), window(limits["secondary"], id: "secondary", title: "Weekly window", camel: true)].compactMap { $0 }
        guard !windows.isEmpty else { throw ParseError.missingLimits }
        return ProviderSnapshot(provider: .codex, windows: windows, updatedAt: now, source: "Codex account")
    }
    public static func codexSession(_ data: Data, fallbackDate: Date? = nil) throws -> ProviderSnapshot {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any], root["type"] as? String == "event_msg", let payload = root["payload"] as? [String: Any], payload["type"] as? String == "token_count" else { throw ParseError.invalid }
        let limits = payload["rate_limits"] as? [String: Any] ?? [:]
        let windows = [window(limits["primary"], id: "primary", title: "Primary window", camel: false), window(limits["secondary"], id: "secondary", title: "Weekly window", camel: false)].compactMap { $0 }
        guard !windows.isEmpty else { throw ParseError.missingLimits }
        // Session token counters are cumulative generation usage; they cannot reliably
        // reveal remaining subscription allowance or current context occupancy.
        return ProviderSnapshot(provider: .codex, windows: windows, updatedAt: date(root["timestamp"]) ?? fallbackDate, source: "Codex session", message: "Last recorded session usage; refreshes when Codex writes a usage event.")
    }
    public static func claude(_ data: Data, fallbackDate: Date? = nil) throws -> ProviderSnapshot {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw ParseError.invalid }
        let limits = root["rate_limits"] as? [String: Any] ?? [:]
        let windows = [window(limits["five_hour"], id: "primary", title: "5-hour window", camel: false), window(limits["seven_day"], id: "secondary", title: "Weekly window", camel: false)].compactMap { $0 }
        var remaining: Int?
        if let context = root["context_window"] as? [String: Any], let size = number(context["context_window_size"]), size > 0, size < Double(Int.max) {
            if let percent = number(context["remaining_percentage"]), (0...100).contains(percent) {
                remaining = Int((size * percent / 100).rounded(.down))
            } else if let current = context["current_usage"] as? [String: Any], let input = number(current["input_tokens"]), input >= 0 {
                let read = number(current["cache_read_input_tokens"]) ?? 0
                let created = number(current["cache_creation_input_tokens"]) ?? 0
                if read >= 0, created >= 0 { remaining = Int(max(0, size - input - read - created)) }
            }
        }
        return ProviderSnapshot(provider: .claude, windows: windows, updatedAt: date(root["updated_at"]) ?? fallbackDate, source: "Claude status line", message: windows.isEmpty ? "Claude has not reported subscription limits yet. Start an active Claude Code session with the status-line bridge enabled." : "Updates during active Claude Code sessions.", contextRemainingTokens: remaining)
    }
    public enum ParseError: Error { case invalid, missingLimits }
}

import CoreFoundation
