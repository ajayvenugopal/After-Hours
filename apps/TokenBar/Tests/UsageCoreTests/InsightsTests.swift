import XCTest
@testable import UsageCore

final class InsightsTests: XCTestCase {
    private var folder: URL!
    override func setUpWithError() throws {
        folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    }
    override func tearDownWithError() throws { try FileManager.default.removeItem(at: folder) }
    private func sample(_ date: Date, _ used: Double, reset: Date?) -> QuotaObservation {
        QuotaObservation(provider: "codex", windowID: "primary", date: date, usedPercent: used, resetsAt: reset)
    }
    func testHistoryDedupRetentionAndPace() throws {
        let ledger = HistoryLedger(url: folder.appendingPathComponent("history.jsonl"))
        let now = Date(timeIntervalSince1970: 1_800_000_000), reset = now.addingTimeInterval(3600)
        try ledger.record([sample(now.addingTimeInterval(-3600), 20, reset: reset), sample(now, 40, reset: reset), sample(now, 40, reset: reset), sample(now.addingTimeInterval(-31 * 86400), 10, reset: reset)], now: now)
        XCTAssertEqual(try ledger.observations().count, 2)
        let pace = try XCTUnwrap(ledger.pace(provider: "codex", windowID: "primary"))
        XCTAssertEqual(pace.percentPerHour, 20, accuracy: 0.001)
        XCTAssertEqual(pace.hoursUntilExhausted, 3, accuracy: 0.001)
    }
    func testPaceRequiresFiveMinutesSameResetAndPositiveDelta() throws {
        let now = Date(timeIntervalSince1970: 1_800_000_000), reset = now.addingTimeInterval(3600)
        for (index, items) in [
            [sample(now.addingTimeInterval(-200), 20, reset: reset), sample(now, 40, reset: reset)],
            [sample(now.addingTimeInterval(-1000), 40, reset: reset), sample(now, 20, reset: reset)],
            [sample(now.addingTimeInterval(-1000), 20, reset: reset.addingTimeInterval(-100)), sample(now, 40, reset: reset)]
        ].enumerated() {
            let ledger = HistoryLedger(url: folder.appendingPathComponent("history\(index).jsonl"))
            try ledger.record(items, now: now)
            XCTAssertNil(try ledger.pace(provider: "codex", windowID: "primary"))
        }
    }
    func testAlertCrossingPersistentDedupAndConfirmedReset() throws {
        let url = folder.appendingPathComponent("alerts.jsonl")
        let engine = AlertEngine(url: url), now = Date(timeIntervalSince1970: 1_800_000_000), reset = Date(timeIntervalSince1970: 1_800_003_600)
        XCTAssertTrue(try engine.evaluate([sample(now, 70, reset: reset)]).isEmpty)
        XCTAssertEqual(try engine.evaluate([sample(now.addingTimeInterval(10), 85, reset: reset)]).map(\.kind), [.lowQuota])
        XCTAssertTrue(try AlertEngine(url: url).evaluate([sample(now.addingTimeInterval(10), 85, reset: reset)]).isEmpty)
        XCTAssertTrue(try engine.evaluate([sample(now.addingTimeInterval(20), 70, reset: reset), sample(now.addingTimeInterval(30), 85, reset: reset)]).isEmpty)
        XCTAssertEqual(try engine.evaluate([sample(reset.addingTimeInterval(1), 3, reset: reset.addingTimeInterval(18000))]).map(\.kind), [.reset])
    }
    func testNoResetAlertForCountdownExpiryOrChangedMetadataAlone() throws {
        let engine = AlertEngine(url: folder.appendingPathComponent("alerts.jsonl")), now = Date(timeIntervalSince1970: 1_800_000_000), reset = Date(timeIntervalSince1970: 1_800_003_600)
        _ = try engine.evaluate([sample(now, 70, reset: reset)])
        XCTAssertTrue(try engine.evaluate([sample(reset.addingTimeInterval(1), 70, reset: reset)]).isEmpty)
        XCTAssertTrue(try engine.evaluate([sample(reset.addingTimeInterval(2), 71, reset: reset.addingTimeInterval(18000))]).isEmpty)
        XCTAssertTrue(try engine.evaluate([sample(reset.addingTimeInterval(3), 5, reset: reset.addingTimeInterval(18000))]).isEmpty)
    }
    func testEventDedupMonthTodayCostAndCacheSemantics() throws {
        let ledger = EventLedger(url: folder.appendingPathComponent("events.jsonl"))
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let today = ISO8601DateFormatter().date(from: "2026-10-07T12:00:00Z")!
        let event = UsageEvent(id: "1", provider: "ollama", model: "m", timestamp: today, inputTokens: 100, outputTokens: 20, cachedTokens: 50)
        let earlier = UsageEvent(id: "2", provider: "codex", model: "m", timestamp: today.addingTimeInterval(-86400), inputTokens: 200, outputTokens: 30, cachedTokens: 100, estimatedCostUSD: 0.02)
        let old = UsageEvent(id: "3", provider: "codex", model: "old", timestamp: today.addingTimeInterval(-31 * 86400), inputTokens: 9999, outputTokens: 0, cachedTokens: 0)
        try ledger.append([event, event, earlier, old]); try ledger.append([event])
        XCTAssertEqual(try ledger.events().count, 3)
        let summary = try ledger.summary(now: today, calendar: calendar)
        XCTAssertEqual(summary.today.totalTokens, 120)
        XCTAssertNil(summary.today.estimatedCostUSD)
        XCTAssertEqual(summary.month.totalTokens, 350)
        XCTAssertEqual(summary.month.cachedTokens, 150)
        XCTAssertEqual(summary.month.estimatedCostUSD, 0.02)
        XCTAssertEqual(summary.month.pricedEventCount, 1)
        XCTAssertEqual(summary.byModel["m"]?.eventCount, 2)
        XCTAssertEqual(summary.daily.count, 2)
    }
    func testCSVQuotesAndFormulaEscapes() throws {
        let ledger = EventLedger(url: folder.appendingPathComponent("events.jsonl"))
        try ledger.append([UsageEvent(id: "=SUM(A1)", provider: "a,b", model: "model\"quoted\nline", timestamp: Date(), inputTokens: 1, outputTokens: 2, cachedTokens: 0)])
        let csv = try ledger.csv()
        XCTAssertTrue(csv.contains("\"'=SUM(A1)\""))
        XCTAssertTrue(csv.contains("\"a,b\""))
        XCTAssertTrue(csv.contains("\"model\"\"quoted\nline\""))
    }
    func testReadsPythonFractionalISO8601Events() throws {
        let url = folder.appendingPathComponent("events.jsonl")
        let json = #"{"id":"python","provider":"gemini","model":"test","timestamp":"2026-10-07T12:00:00.123456+00:00","inputTokens":100,"outputTokens":20,"cachedTokens":5}"# + "\n"
        try Data(json.utf8).write(to: url)
        let events = try EventLedger(url: url).events()
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events.first?.id, "python")
    }

}
