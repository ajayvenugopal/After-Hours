import Foundation

public struct ResetCheckResult: Sendable {
    public enum Status: Sendable { case confirmed, available, limited, unverified }
    public let status: Status
    public let title: String
    public let message: String
    public let checkedAt: Date

    public static func evaluate(current: ProviderSnapshot, previous: ProviderSnapshot?, now: Date = Date()) -> Self {
        func result(_ status: Status, _ title: String, _ message: String) -> Self {
            Self(status: status, title: title, message: message, checkedAt: now)
        }
        guard current.source == "Codex account", let updated = current.updatedAt,
              now.timeIntervalSince(updated) <= 120, now.timeIntervalSince(updated) >= -60,
              !current.windows.isEmpty else {
            return result(.unverified, "Account check unavailable",
                          current.provider == .claude
                          ? "Claude updates from an active Claude Code session. Open account usage to verify your current allowance."
                          : "Could not read live account limits. Cached session data cannot confirm a reset. Open account usage to verify.")
        }
        guard !current.windows.contains(where: { $0.resetsAt.map { $0 <= now } ?? false }) else {
            return result(.unverified, "Reset still pending", "The account still reports an expired window. Check again once updated limits are available.")
        }
        let blocked = current.windows.filter { $0.remainingPercent <= 0 }
        if !blocked.isEmpty {
            return result(.limited, "Quota not available", "\(blocked.map(\.title).joined(separator: ", ")) exhausted. The account has not restored usable quota yet.")
        }
        let reset = current.windows.contains { window in
            guard let old = previous?.windows.first(where: { $0.id == window.id }),
                  let oldReset = old.resetsAt, let newReset = window.resetsAt,
                  let previousDate = previous?.updatedAt, updated > previousDate else { return false }
            return oldReset <= updated && newReset > oldReset && window.usedPercent < old.usedPercent
        }
        let window = current.windows.first { $0.id == "primary" || $0.id == "session" } ?? current.windows[0]
        return result(reset ? .confirmed : .available, reset ? "Reset confirmed · quota available" : "Quota available",
                      "\(window.title): \(Int(window.remainingPercent.rounded()))% remaining. Verified with your Codex account.")
    }
}
