import XCTest
@testable import UsageCore

final class UsageParserTests: XCTestCase {
    func testAccountLimitsAndClamping() throws {
        let value = try UsageParser.codexRPC(Data(#"{"result":{"rateLimits":{"primary":{"usedPercent":23,"windowDurationMins":300,"resetsAt":1800000000},"secondary":{"usedPercent":120,"windowDurationMins":10080}}}}"#.utf8))
        XCTAssertEqual(value.windows.count, 2)
        XCTAssertEqual(value.windows[0].remainingPercent, 77)
        XCTAssertEqual(value.windows[0].title, "5-hour window")
        XCTAssertEqual(value.windows[0].resetsAt, Date(timeIntervalSince1970: 1800000000))
        XCTAssertEqual(value.windows[1].remainingPercent, 0)
        XCTAssertNil(value.windows[1].resetsAt)
        XCTAssertNil(value.contextRemainingTokens)
    }
    func testGroupedAccountLimits() throws {
        let value = try UsageParser.codexRPC(Data(#"{"result":{"rateLimitsByLimitId":{"codex":{"primary":{"usedPercent":15}}}}}"#.utf8))
        XCTAssertEqual(value.windows.first?.usedPercent, 15)
    }
    func testSessionDoesNotMisrepresentCumulativeTokensAsCapacity() throws {
        let value = try UsageParser.codexSession(Data(#"{"timestamp":"2026-10-07T12:00:00Z","type":"event_msg","payload":{"type":"token_count","info":{"model_context_window":200000,"total_token_usage":{"total_tokens":150000}},"rate_limits":{"primary":{"used_percent":-5,"window_minutes":300,"resets_at":1800000000}}}}"#.utf8))
        XCTAssertEqual(value.windows.first?.remainingPercent, 100)
        XCTAssertNotNil(value.updatedAt)
        XCTAssertNil(value.contextRemainingTokens)
    }
    func testClaudeRemainingPercentageAndRateLimits() throws {
        let value = try UsageParser.claude(Data(#"{"updated_at":"2026-10-07T12:00:00.000Z","rate_limits":{"five_hour":{"used_percentage":35,"resets_at":1800000000},"seven_day":{"used_percentage":20,"resets_at":1800500000}},"context_window":{"context_window_size":200000,"remaining_percentage":60}}"#.utf8))
        XCTAssertEqual(value.windows.count, 2)
        XCTAssertEqual(value.contextRemainingTokens, 120000)
        XCTAssertNotNil(value.updatedAt)
    }
    func testClaudeContextCountsOnlyCurrentInputAndCache() throws {
        let value = try UsageParser.claude(Data(#"{"context_window":{"context_window_size":200000,"total_input_tokens":999999,"current_usage":{"input_tokens":10000,"cache_read_input_tokens":20000,"cache_creation_input_tokens":5000,"output_tokens":9000}}}"#.utf8))
        XCTAssertEqual(value.contextRemainingTokens, 165000)
        XCTAssertTrue(value.windows.isEmpty)
        XCTAssertNotNil(value.message)
    }
    func testNullOrInvalidContextIsUnknown() throws {
        for json in [#"{"context_window":{"context_window_size":200000,"current_usage":null}}"#, #"{"context_window":{"context_window_size":200000,"remaining_percentage":101}}"#, #"{"context_window":{"context_window_size":-1,"remaining_percentage":50}}"#] {
            XCTAssertNil(try UsageParser.claude(Data(json.utf8)).contextRemainingTokens)
        }
    }
    func testMalformedMissingAndBooleanLimits() {
        for json in ["no json", "{}", #"{"result":{"rateLimits":{"primary":{"usedPercent":true}}}}"#] {
            XCTAssertThrowsError(try UsageParser.codexRPC(Data(json.utf8)))
        }
    }
    func testResetMissingDoesNotInventDate() throws {
        let value = try UsageParser.claude(Data(#"{"rate_limits":{"five_hour":{"used_percentage":70,"resets_at":"garbage"}}}"#.utf8))
        XCTAssertNil(value.windows.first?.resetsAt)
        XCTAssertEqual(value.windows.first?.remainingPercent, 30)
    }
}
