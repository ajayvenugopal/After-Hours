import XCTest
@testable import UsageCore

final class ResetCheckTests: XCTestCase {
    let now = Date(timeIntervalSince1970: 1_800_000_000)
    func snapshot(used: Double, reset: Date, date: Date? = nil, source: String = "Codex account", weekly: Double = 10) -> ProviderSnapshot {
        ProviderSnapshot(provider: .codex, windows: [
            UsageWindow(id: "primary", title: "5-hour window", usedPercent: used, resetsAt: reset),
            UsageWindow(id: "secondary", title: "Weekly window", usedPercent: weekly, resetsAt: now.addingTimeInterval(86400))
        ], updatedAt: date ?? now, source: source)
    }
    func testConfirmsRolloverOnlyWhenAccountRestoresQuota() {
        let old = snapshot(used: 90, reset: now.addingTimeInterval(-1), date: now.addingTimeInterval(-20))
        let current = snapshot(used: 0, reset: now.addingTimeInterval(18000))
        XCTAssertEqual(ResetCheckResult.evaluate(current: current, previous: old, now: now).status, .confirmed)
        let unchanged = snapshot(used: 90, reset: now.addingTimeInterval(18000))
        XCTAssertEqual(ResetCheckResult.evaluate(current: unchanged, previous: old, now: now).status, .available)
    }
    func testExpiredOrCachedDataCannotVerifyReset() {
        XCTAssertEqual(ResetCheckResult.evaluate(current: snapshot(used: 100, reset: now.addingTimeInterval(-1)), previous: nil, now: now).status, .unverified)
        XCTAssertEqual(ResetCheckResult.evaluate(current: snapshot(used: 0, reset: now.addingTimeInterval(18000), source: "Codex session"), previous: nil, now: now).status, .unverified)
        XCTAssertEqual(ResetCheckResult.evaluate(current: snapshot(used: 0, reset: now.addingTimeInterval(18000), date: now.addingTimeInterval(-121)), previous: nil, now: now).status, .unverified)
    }
    func testExhaustedWeeklyQuotaBlocksAccountAvailability() {
        XCTAssertEqual(ResetCheckResult.evaluate(current: snapshot(used: 10, reset: now.addingTimeInterval(18000), weekly: 100), previous: nil, now: now).status, .limited)
    }
    func testClaudeNeedsAccountVerification() {
        XCTAssertEqual(ResetCheckResult.evaluate(current: ProviderSnapshot(provider: .claude), previous: nil, now: now).status, .unverified)
    }
}
