import XCTest
@testable import UsageCore

final class NativeSessionEventsTests: XCTestCase {
    func testCodexDeduplicatesCumulativeCountersAndIgnoresRateOnlyRecords() {
        let lines = #"{"type":"turn_context","payload":{"model":"gpt-test"}}"# + "\n" +
        #"{"type":"event_msg","timestamp":"2026-10-07T12:00:00Z","payload":{"type":"token_count","info":{"total_token_usage":{"total_tokens":150},"last_token_usage":{"input_tokens":100,"output_tokens":50,"cached_input_tokens":20}}}}"# + "\n" +
        #"{"type":"event_msg","timestamp":"2026-10-07T12:01:00Z","payload":{"type":"token_count","info":{"total_token_usage":{"total_tokens":150},"last_token_usage":{"input_tokens":100,"output_tokens":50,"cached_input_tokens":20}}}}"# + "\n" +
        #"{"type":"event_msg","timestamp":"2026-10-07T12:02:00Z","payload":{"type":"token_count","info":null,"rate_limits":{"primary":{"used_percent":15}}}}"#
        let events = NativeSessionEvents.parseCodexLines(Data(lines.utf8), sessionID: "private/path/session")
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events.first?.model, "gpt-test")
        XCTAssertEqual(events.first?.inputTokens, 100)
        XCTAssertEqual(events.first?.cachedTokens, 20)
        XCTAssertEqual(events.first?.id.count, 64)
        XCTAssertFalse(events.first?.id.contains("private") ?? true)
        XCTAssertEqual(events.first?.timestamp, ISO8601DateFormatter().date(from: "2026-10-07T12:00:00Z"))
        XCTAssertEqual(events.first?.id, NativeSessionEvents.parseCodexLines(Data(lines.utf8), sessionID: "private/path/session").first?.id)
    }
    func testCodexCountersFromDifferentSessionsRemainDistinct() {
        let data = Data(#"{"type":"event_msg","timestamp":"2026-10-07T12:00:00Z","payload":{"type":"token_count","info":{"total_token_usage":{"total_tokens":150},"last_token_usage":{"input_tokens":100,"output_tokens":50}}}}"#.utf8)
        XCTAssertNotEqual(NativeSessionEvents.parseCodexLines(data, sessionID: "a").first?.id, NativeSessionEvents.parseCodexLines(data, sessionID: "b").first?.id)
    }
    func testClaudeFinalMessageUsageIncludesCachesAndIgnoresUsers() {
        let lines = #"{"type":"assistant","timestamp":"2026-10-07T12:00:00Z","message":{"id":"msg1","model":"claude-test","content":"private text","usage":{"input_tokens":100,"output_tokens":5,"cache_read_input_tokens":200,"cache_creation_input_tokens":50}}}"# + "\n" +
        #"{"type":"assistant","timestamp":"2026-10-07T12:00:01Z","message":{"id":"msg1","model":"claude-test","usage":{"input_tokens":100,"output_tokens":30,"cache_read_input_tokens":200,"cache_creation_input_tokens":50}}}"# + "\n" +
        #"{"type":"user","timestamp":"2026-10-07T12:00:02Z","message":{"id":"msg2","usage":{"input_tokens":9999,"output_tokens":9999}}}"#
        let events = NativeSessionEvents.parseClaudeLines(Data(lines.utf8), sessionID: "session")
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events.first?.inputTokens, 350)
        XCTAssertEqual(events.first?.outputTokens, 30)
        XCTAssertEqual(events.first?.cachedTokens, 200)
        XCTAssertNil(events.first?.estimatedCostUSD)
    }
    func testPartialOrMalformedRowsDoNotPreventLaterRecords() {
        let lines = "partial garbage\n" + #"{"type":"assistant","timestamp":"2026-10-07T12:00:01.123Z","message":{"id":"msg1","model":"claude-test","usage":{"input_tokens":1,"output_tokens":2}}}"# + "\n{truncated"
        XCTAssertEqual(NativeSessionEvents.parseClaudeLines(Data(lines.utf8), sessionID: "s").count, 1)
    }
}
