import XCTest
@testable import UsageCore

final class CodexTransportTests: XCTestCase {
    private func helper(_ source: String) throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("tokenbar-helper-\(UUID().uuidString).py")
        try ("#!/usr/bin/python3\n" + source).write(to: url, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: url.path)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }
    func testHelperExitingBeforeReplyIsRecoverable() throws {
        let executable = try helper("import sys\nsys.exit(0)\n")
        XCTAssertThrowsError(try CodexRPC.read(executable: executable))
    }
    func testHelperClosingInputDuringHandshakeDoesNotTerminateApp() throws {
        let executable = try helper("import os, time\nos.close(0)\nprint('{\"id\":1,\"result\":{}}', flush=True)\ntime.sleep(0.4)\n")
        XCTAssertThrowsError(try CodexRPC.read(executable: executable))
    }
    func testLiveHelperRepliesBeforeItsOutputPipeCloses() throws {
        let executable = try helper("""
        import sys, json
        for line in sys.stdin:
            request = json.loads(line)
            if request.get('method') == 'initialize':
                print(json.dumps({'id': request['id'], 'result': {}}), flush=True)
            elif request.get('method') == 'account/rateLimits/read':
                print(json.dumps({'id': request['id'], 'result': {'rateLimits': {'primary': {'usedPercent': 25, 'windowDurationMins': 300}}}}), flush=True)
        """)
        let start = Date()
        let data = try CodexRPC.read(executable: executable)
        let snapshot = try UsageParser.codexRPC(data)
        XCTAssertEqual(snapshot.windows.first?.remainingPercent, 75)
        XCTAssertLessThan(Date().timeIntervalSince(start), 3)
    }
}
